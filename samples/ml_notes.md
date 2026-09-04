# Gradient Descent
Gradient descent is an optimization algorithm used to minimize a loss function by iteratively moving in the direction of steepest descent. At every iteration the parameters are updated by subtracting the gradient of the loss with respect to those parameters, scaled by the learning rate. It is the workhorse behind almost all modern neural network training.

# Learning Rate
The learning rate is a hyperparameter that determines how large a step the optimizer takes on each update. If the learning rate is too large the optimization can oscillate or diverge entirely, and if it is too small convergence becomes extremely slow. Learning rate schedules decay the value over time to combine fast early progress with stable late convergence.

# Stochastic Gradient Descent
Stochastic gradient descent estimates the gradient using a mini batch of samples rather than the full dataset. This makes every update far cheaper to compute and introduces gradient noise that can help the optimizer escape shallow local minima and saddle points during training. Batch size therefore trades off gradient variance against hardware throughput.

# Momentum
Momentum accumulates an exponentially decaying moving average of past gradients and uses it to accelerate the optimizer along consistent directions while damping oscillations across steep ravines. Nesterov momentum improves on this by evaluating the gradient at the look ahead position rather than the current one.

# Adam Optimizer
Adam combines momentum with per parameter adaptive learning rates derived from a running estimate of the second moment of the gradients. Bias correction terms compensate for the zero initialization of both moment estimates during the first few steps of training.
