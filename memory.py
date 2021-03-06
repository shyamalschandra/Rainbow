import random
from collections import deque, namedtuple
import torch
from torch.autograd import Variable


Transition = namedtuple('Transition', ('state', 'action', 'next_state', 'reward'))


class ReplayMemory():
  def __init__(self, capacity, history_length, discount=None, multi_step=None, priority_exponent=None, priority_weight=None):
    self.capacity = capacity
    self.history = history_length
    self.discount = discount
    self.n = multi_step
    self.priority_exponent = priority_exponent
    self.priority_weight = priority_weight  # Initial value, annealed to 1 over course of training
    self.t = 0  # Internal episode timestep counter
    self.states = deque([], maxlen=capacity)
    self.actions = deque([], maxlen=capacity)
    self.rewards = deque([], maxlen=capacity)
    self.timesteps = deque([], maxlen=capacity)
    self.nonterminals = deque([], maxlen=capacity)  # Non-terminal states

  # Add empty states to prepare for new episode
  def preappend(self):
    self.t = 0
    # Blank transitions from before episode
    for h in range(-self.history + 1, 0):
      self.timesteps.append(h)
      self.states.append(torch.ByteTensor(84, 84).zero_())  # Add blank state
      self.actions.append(None)
      self.rewards.append(None)
      self.nonterminals.append(True)

  def append(self, state, action, reward):
    # Add state, action and reward at time t
    self.timesteps.append(self.t)
    if state is None:
      self.states.append(torch.ByteTensor(84, 84).zero_())  # Add blank state (used to replace terminal state)
      self.nonterminals.append(False)
    else:
      self.states.append(state[-1].mul(255).byte())  # Only store last frame and discretise to save memory
      self.nonterminals.append(True)
    self.actions.append(action)
    self.rewards.append(reward)  # Technically from time t + 1, but kept at t for all buffers to be in sync
    self.t += 1

  def sample(self, batch_size):
    # Find indices for valid samples
    valid = list(map(lambda x: x >= 0, self.timesteps))  # Valid frames by timestep
    valid = [a and b for a, b in zip(valid, valid[self.n:] + [False] * self.n)]  # Cannot use terminal states (- n+1)/state at end of memory
    valid[:self.history - 1] = [False] * (self.history - 1)  # Cannot form stack from initial frames
    inds = random.sample([i for i, v in zip(range(len(valid)), valid) if v], batch_size)

    # Create stack of states and nth next states
    state_stack, next_state_stack = [], []
    for h in reversed(range(self.history)):
      state_stack.append(torch.stack([self.states[i - h] for i in inds], 0))
      next_state_stack.append(torch.stack([self.states[i + self.n - h] for i in inds], 0))  # nth next state
    states = Variable(torch.stack(state_stack, 1).float().div_(255))  # Un-discretise
    next_states = Variable(torch.stack(next_state_stack, 1).float().div_(255), volatile=True)

    actions = torch.LongTensor([self.actions[i] for i in inds])

    # Calculate truncated n-step discounted return R^n = Σ_k=0->n-1 (γ^k)R_t+k+1
    returns = [self.rewards[i] for i in inds]
    for n in range(1, self.n):
      returns = [R + self.discount ** n * self.rewards[i + n] for R, i in zip(returns, inds)]
    returns = torch.Tensor(returns)

    nonterminals = torch.Tensor([self.nonterminals[i + self.n] for i in inds]).unsqueeze(1)  # Mask for non-terminal nth next states

    return states, actions, returns, next_states, nonterminals

  # Set up internal state for iterator
  def __iter__(self):
    # Find indices for valid samples
    valid = list(map(lambda x: x >= 0, self.timesteps))  # Valid frames by timestep
    valid = [a and b for a, b in zip(valid, valid[1:] + [False])]  # Cannot use terminal states/state at end of memory
    valid[:self.history - 1] = [False] * (self.history - 1)  # Cannot form stack from initial frames
    self.current_ind = 0
    self.valid_inds = [i for i, v in zip(range(len(valid)), valid) if v]
    return self

  # Return valid states for validation
  def __next__(self):
    if self.current_ind == len(self.valid_inds):
      raise StopIteration
    # Create stack of states and nth next states
    state_stack = []
    for h in reversed(range(self.history)):
      state_stack.append(self.states[self.valid_inds[self.current_ind - h]])
    state = Variable(torch.stack(state_stack, 0).float().div_(255), volatile=True)  # Agent will turn into batch
    self.current_ind += 1
    return state

# TODO: Prioritised experience replay memory
