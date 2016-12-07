from datetime import timedelta
from nio.modules.scheduler import Job


class HeartbeatHandler(object):
    """ A class that can send and handle socket.io heartbeats """

    def __init__(self, send_callback, timeout_callback, heartbeat_interval,
                 heartbeat_timeout, logger):
        """ Create a heartbeat handler with some timing parameters

        Args:
            send_callback (func): A function to call when sending heartbeats
            timeout_callback (func): A function to call when a heartbeat
                response is not received in time
            heartbeat_interval (int): How often (secs) to send heartbeats
            heartbeat_timeout (int): How long (secs) to wait for a heartbeat
                response from the server
            logger (Logger): Where to log information and diagnostics
        """
        super().__init__()
        self._heartbeat_func = send_callback
        self._timeout_func = timeout_callback
        self._heartbeat_job = None
        self._heartbeat_expiry_job = None
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_timeout = heartbeat_timeout
        self.logger = logger

    def handle_heartbeat_response(self):
        """ Handle a response heartbeat from the server """
        self.logger.debug("Heartbeat PONG received")
        # Restart the heartbeat expiry job
        self._start_expiry_job()

    def start_heartbeats(self):
        """ Start a job which will periodically send heartbeats to the server.

        This method will also start a job that will wait for responses in case
        the server doesn't respond in time.
        """
        # Since we are starting a new heartbeat cycle, cancel anything
        # that was outstanding
        self.stop_heartbeats()

        # Start a job that will send heartbeats indefinitely
        self._heartbeat_job = Job(
            self._heartbeat_func,
            timedelta(seconds=self._heartbeat_interval),
            repeatable=True)

        # Also start a job that will wait for heartbeat timeouts
        self._start_expiry_job()

    def stop_heartbeats(self):
        self._stop_expiry_job()
        self._stop_heartbeat_job()

    def _start_expiry_job(self):
        # Stop the existing job, if it exists
        self._stop_expiry_job()

        self._heartbeat_expiry_job = Job(
            self._no_heartbeat_response,
            timedelta(seconds=self._heartbeat_timeout),
            repeatable=False)

    def _stop_heartbeat_job(self):
        """ Cancel and remove the job that sends heartbeats """
        if self._heartbeat_job:
            self._heartbeat_job.cancel()
        self._heartbeat_job = None

    def _stop_expiry_job(self):
        """ Cancel and remove the job that waits for responses """
        if self._heartbeat_expiry_job:
            self._heartbeat_expiry_job.cancel()
        self._heartbeat_expiry_job = None

    def _no_heartbeat_response(self):
        """ Called when a heartbeat request has expired.

        All we are going to do in here is tell the client we timed out. We
        don't want to stop sending heartbeats, maybe the next one will go
        through and the server will respond which will kick start the expiry
        process again.
        """
        self.logger.warning("No heartbeat response was received...reconnecting")
        self._timeout_func()
