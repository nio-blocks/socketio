from enum import Enum
from nio.metadata.properties import PropertyHolder, ObjectProperty, \
    BoolProperty, IntProperty, SelectProperty, FloatProperty
from .strategy import BackoffStrategy
from .strategies import LinearBackoff, ExponentialBackoff


class RetryStrategies(Enum):
    linear = LinearBackoff
    exponential = ExponentialBackoff


class RetryOptions(PropertyHolder):
    """ Options the block can be configured with to control how it retries.

    The properties will be passed to the backoff strategy's constructor.
    """

    strategy = SelectProperty(RetryStrategies, title="Strategy to Use",
                              default=RetryStrategies.linear, allow_expr=False)
    max_retry = IntProperty(title="Max Number of Retries", default=5,
                            allow_expr=False)
    multiplier = FloatProperty(title="Retry Multiplier", default=1,
                               allow_expr=False)
    indefinite = BoolProperty(title="Continue Indefinitely?", default=False,
                              allow_expr=False)

    def get_options_dict(self):
        return {
            "max_retry": self.max_retry,
            "multiplier": self.multiplier,
            "indefinite": self.indefinite
        }


class Retry(object):
    """ A block mixin that provides retry functionality.

    By including this mixin, your block will have access to a method that can
    retry on failure. This is useful when performing tasks that have a chance
    of failing but can then work upon retrying. Example use cases are database
    queries or other requests over a network.

    When this mixin is added to a block, some hidden retry configuration
    options will be added to the block. These options allow the block
    configurer to determine how retries should occur, including what strategy
    should be used.

    Block developers can implement their own backoff strategies and employ
    those instead by overriding the setup_backoff_strategy method.

    How to use this mixin:
        1. Configure your block by selecting a backoff strategy as well as
        providing some options to determine how long it will wait between
        retries.

        2. Call execute_with_retry with the function that you want to execute.
        If the target function raises an exception, it will retry until it
        either succeeds or the backoff strategy has decided it should stop
        retrying. If that occurs, execute_with_retry will raise the exception
        that the target function raised originally.

        3. Optionally, override before_retry to write custom code that will be
        performed before attempting a retry.
    """

    retry_options = ObjectProperty(RetryOptions, title="Retry Options",
                                   visible=True, default=RetryOptions())

    def configure(self, context):
        """ This implementation will use the configured backoff strategy """
        super().configure(context)
        self.setup_backoff_strategy()

    def setup_backoff_strategy(self):
        """ Define which backoff strategy the block should use.

        This implementation will use the selected backoff strategy from the
        configured retry options and pass other configured options as kwargs.

        Block developers can override this function to use a custom backoff
        strategy.
        """
        self.use_backoff_strategy(
            self.retry_options.strategy.value,
            **(self.retry_options.get_options_dict()))

    def execute_with_retry(self, execute_method, *args, **kwargs):
        """ Execute a method and retry if it raises an exception

        Args:
            execute_method (callable): A function to attempt to execute. The
                function may be called multiple times if retries occur.
            args/kwargs: Optional arguments to pass to the execute method

        Returns:
            The result of execute_method upon success.

        Raises:
            Exception: The exception that execute_method raised when the
                backoff strategy decided to stop retrying.
        """
        # Save a stringified version of the method's name
        # If it doesn't define __name__, use however we should stringify
        execute_method_name = getattr(
            execute_method, '__name__', str(execute_method))
        while True:
            try:
                result = execute_method(*args, **kwargs)
                # If we got here, the request succeeded, let the backoff
                # strategy know then return the result
                self._backoff_strategy.request_succeeded()
                return result
            except Exception as exc:
                self._logger.warning(
                    "Retryable execution on method {} failed".format(
                        execute_method_name, exc_info=True))
                self._backoff_strategy.request_failed(exc)
                should_retry = self._backoff_strategy.should_retry()
                if not should_retry:
                    # Backoff strategy has said we're done retrying,
                    # so re-raise the exception
                    self._logger.exception(
                        "Out of retries for method {}.".format(
                            execute_method_name))
                    raise
                else:
                    # Backoff strategy has instructed us to retry again. First
                    # let the strategy do any waiting, then execute any
                    # pre-work before looping and executing the method again
                    self._backoff_strategy.wait_for_retry()
                    self._logger.info("Retrying method execution")
                    self.before_retry(*args, **kwargs)

    def use_backoff_strategy(self, strategy, *args, **kwargs):
        """ Tell this mixin which backoff strategy to use.

        This method should be called in a block's configure method.

        Args:
            strategy (class): A subclass of BackoffStrategy to use in this
                block when retrying
            args/kwargs: Optional arguments to pass to the constructor of the
                backoff strategy
        """
        if not issubclass(strategy, BackoffStrategy):
            raise TypeError("Backoff strategy must subclass BackoffStrategy")
        self._backoff_strategy = strategy(*args, **kwargs)
        self._backoff_strategy.use_logger(self._logger)

    def before_retry(self, *args, **kwargs):
        """ Perform any actions before the next retry occurs.

        Override this in your block to take action before a retry is attempted.
        This would be the function where you would make any reconnections or
        any other behavior that may make the next retry attempt succeed.
        """
        pass  # pragma: no cover