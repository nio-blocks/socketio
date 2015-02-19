from datetime import timedelta
from nio.common.block.base import Block
from nio.metadata.properties import BoolProperty, IntProperty, \
    StringProperty, ExpressionProperty, TimeDeltaProperty
from nio.modules.scheduler import Job
from nio.common.signal.base import Signal
from nio.common.signal.status import BlockStatusSignal
from nio.common.block.controller import BlockStatus


class SocketIOBase(Block):

    """ A base block for communicating with a socket.io server.

    Properties:
        host (str): location of the socket.io server.
        port (int): socket.io server port.
        room (str): socket.io room.
        content (Expression): Content to send to socket.io room.
        listen (bool): Whether or not the block should listen to messages
            FROM the SocketIo room.

    """
    host = StringProperty(title='SocketIo Host', default="127.0.0.1")
    port = IntProperty(title='Port', default=443)
    room = StringProperty(title='SocketIo Room', default="default")
    content = ExpressionProperty(
        title='Content', default="{{json.dumps($to_dict(), default=str)}}")
    listen = BoolProperty(title="Listen to SocketIo Room", default=False)
    max_retry = TimeDeltaProperty(
        title="Max Retry Time", default={"seconds": 300})

    def __init__(self):
        super().__init__()
        self._sid = ""
        self._hb_timeout = -1  # Heartbeat timeout
        self._close_timeout = -1  # Close connection timeout
        self._transports = ""  # Valid transports
        self._client = None
        self._socket_url_base = ""
        self._timeout = 1
        self._connection_job = None

    def configure(self, context):
        super().configure(context)
        self._build_socket_url_base()

        # Should connect now so we're ready to process signals
        self._connect_to_socket()

    def stop(self):
        """ Stop the block by closing the client.

        """
        super().stop()
        self._logger.debug("Shutting down socket.io client")

        # Cancel any pending reconnects
        if self._connection_job:
            self._connection_job.cancel()

        self._client.close()

    def handle_reconnect(self):
        self._timeout = self._timeout or 1
        self._client = None

        if self._connection_job is not None:
            self._logger.warning("Reconnection job already scheduled")
            return

        # Make sure our timeout is not getting out of hand
        if (self._timeout <= self.max_retry.total_seconds()):
            self._logger.warning("Attempting to reconnect in {0} seconds."
                                 .format(self._timeout))
            self._connection_job = Job(
                self._connect_to_socket,
                timedelta(seconds=self._timeout),
                repeatable=False)
        else:
            self._logger.error(
                "Failed to reconnect after unexpected close. Giving up.")
            status_signal = BlockStatusSignal(
                BlockStatus.error, 'Out of retries.')

            # Leaving source for backwards compatibility
            # In the future, you will know that a status signal is a block
            # status signal when it contains service_name and name
            #
            # TODO: Remove when source gets added to status signals in nio
            setattr(status_signal, 'source', 'Block')

            self.notify_management_signal(status_signal)

    def handle_data(self, data):
        """Handle data coming from the web socket

        data will be a dictionary, *most likely* containing an event and data
        that was sent, in the form of a python object.
        """
        if 'event' not in data or data['event'] != 'recvData':
            # We don't care about this event, it's not data
            return
        try:
            sig = Signal()
            for dataKey in data['data']:
                setattr(sig, dataKey, data['data'][dataKey])
            self.notify_signals([sig])
        except Exception as e:
            self._logger.warning("Could not parse socket data: %s" % e)

    def _connect_to_socket(self):
        try:
            # Don't need the job any more
            self._connection_job = None
            self._do_handshake()

            url = self._get_ws_url()
            self._logger.debug("Connecting to %s" % url)
            self._create_client(url)
            self._logger.info("Connected to socket successfully")

            # Reset the timeout
            self._timeout = 1
        except Exception as e:
            self._timeout *= 2
            self._logger.error(e)
            self.handle_reconnect()

    def process_signals(self, signals):
        """ Send content to the socket.io room.

        """
        for signal in signals:
            try:
                message = self.content(signal)
            except Exception as e:
                self._logger.error(
                    "Content evaluation failed: {0}: {1}".format(
                        type(e).__name__, str(e))
                )
                continue

            # Make sure the client is set up and accepting connections
            if self._client is None or self._client.terminated:
                self._logger.warning(
                    "Tried to send to a non-existent or "
                    "terminated web socket, dropping the signal")
                continue

            self._client.send_event('pub', message)

    def _create_client(self, url):
        """ To be overridden """
        pass

    def _build_socket_url_base(self):
        """ To be overridden """
        pass

    def _do_handshake(self):
        """ To be overridden """
        pass

    def _get_ws_url(self):
        """ To be overridden """
        pass
