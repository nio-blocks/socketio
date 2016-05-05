import requests
import json
import re
from enum import Enum
from datetime import timedelta
from .client import SocketIOWebSocketClient
from .client_1 import SocketIOWebSocketClientV1
from .retry.retry import Retry
from nio.common.discovery import Discoverable, DiscoverableType
from nio.common.block.base import Block
from nio.metadata.properties import BoolProperty, IntProperty, \
    StringProperty, ExpressionProperty, SelectProperty, VersionProperty
from nio.modules.scheduler import Job
from nio.common.signal.base import Signal
from nio.common.signal.status import BlockStatusSignal
from nio.common.block.controller import BlockStatus


class SocketIOVersion(Enum):
    v0 = '0.9.x'
    v1 = '1.x.x'


@Discoverable(DiscoverableType.block)
class SocketIO(Retry, Block):

    """ A block for communicating with a socket.io server.

    Properties:
        host (str): location of the socket.io server.
        port (int): socket.io server port.
        room (str): socket.io room.
        content (Expression): Content to send to socket.io room.
        listen (bool): Whether or not the block should listen to messages
            FROM the SocketIo room.
        version (enum): Which version of socketIO to use

    """
    version = VersionProperty('1.1.0')
    host = StringProperty(title='SocketIo Host', default="127.0.0.1")
    port = IntProperty(title='Port', default=443)
    room = StringProperty(title='SocketIo Room', default="default")
    content = ExpressionProperty(
        title='Content', default="{{json.dumps($to_dict(), default=str)}}",
        visible=False)
    listen = BoolProperty(title="Listen to SocketIo Room", default=False)
    socketio_version = SelectProperty(
        SocketIOVersion, title='Socket.IO Version', default=SocketIOVersion.v1)

    def __init__(self):
        super().__init__()
        self._sid = ""
        self._heartbeat_job = None
        self._hb_interval = -1  # Heartbeat interval
        self._hb_timeout = -1  # Heartbeat timeout
        self._transports = ""  # Valid transports
        self._client = None
        self._socket_url_base = ""
        self._stopping = False

    def configure(self, context):
        super().configure(context)
        self._build_socket_url_base()

        # Should connect now so we're ready to process signals
        self._connect_to_socket()

    def stop(self):
        """ Stop the block by closing the client.

        """
        self._stopping = True
        self._logger.debug("Shutting down socket.io client")

        self._stop_heartbeats()
        self._close_client()
        super().stop()

    def handle_reconnect(self):
        # Stop sending heartbeats immediately
        # We do this here because we don't want a heartbeat going out when
        # the client is trying to close, sometimes that can take some time
        self._stop_heartbeats()

        # Now that we won't send heartbeats anymore, let's close the client
        self._close_client()

        # Don't need to reconnect if we are stopping, the close was expected
        if self._stopping:
            return

        try:
            self.execute_with_retry(self._connect_to_socket)
        except:
            self._logger.exception("Failed to reconnect - giving up")

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
        self._do_handshake()

        url = self._get_ws_url()
        self._logger.info("Connecting to %s" % url)
        self._create_client(url)
        self._logger.info("Connected to socket successfully")

    def process_signals(self, signals):
        """ Send content to the socket.io room. """

        # Don't do any processing or sending if the block is stopping.
        # The connection may be closed and we don't want to re-open
        if self._stopping:
            return

        for signal in signals:
            try:
                message = self.content(signal)
            except:
                self._logger.exception("Content evaluation failed")
                continue

            # Make sure the client is set up and accepting connections
            if self._client is None or self._client.terminated:
                self._logger.warning(
                    "Tried to send to a non-existent or "
                    "terminated web socket, dropping the signal")
                continue

            self._client.send_event('pub', message)

    def _is_version_1(self):
        return self.socketio_version == SocketIOVersion.v1

    def _get_socket_client(self):
        """ Get the WS client class to use

        Returns:
            class: a WebSocketClient class for the configured version of
                socket.io
        """
        if self._is_version_1():
            return SocketIOWebSocketClientV1

        return SocketIOWebSocketClient

    def _send_heartbeat(self):
        """ Send a heartbeat through the socket client.

        This is likely only used in version 1, version 0 sends heartbeats
        when requested to, so the client takes care of it.
        """
        if self._client and not self._client.terminated:
            self._client._send_heartbeat()
        else:
            self._logger.warning(
                "Cannot send heartbeat to non-connected socket")

    def _stop_heartbeats(self):
        """ Stop any scheduled heartbeat sending job.

        Most likely only in use in version 1, but safely callable
        regardless.
        """
        if self._heartbeat_job:
            self._heartbeat_job.cancel()
            self._heartbeat_job = None

    def _close_client(self):
        """ Safely close the client and remove the reference """
        try:
            # Try to close the client if it's open
            if self._client:
                self._client.close()
        except:
            # If we couldn't close, it's fine. Either the client wasn't
            # opened or it didn't want to respond. That's what we get for
            # being nice and cleaning up our connection
            self._logger.info("Error closing client", exc_info=True)
        finally:
            self._client = None

    def _create_client(self, url):
        """ Create a WS client object.

        This will close any existing clients and re-create a client
        object.

        By the time this function returns, the client is connected and
        ready to send data.
        """
        # In case the client is sticking around, close it before creating a
        # new one
        self._close_client()

        # If there is a pending heartbeat job, kill it
        # we will re-create after connecting
        self._stop_heartbeats()

        # Get the right version of the socket client class and instantiate it
        self._client = self._get_socket_client()(url, self)
        self._client.connect()

        # Schedule the heartbeat job only in version 1
        if self._is_version_1():
            self._heartbeat_job = Job(
                self._send_heartbeat,
                timedelta(seconds=self._hb_interval),
                repeatable=True)

    def _build_socket_url_base(self):
        if self._is_version_1():
            self._socket_url_base = "{}:{}/socket.io/".format(
                self.host, self.port)
        else:
            self._socket_url_base = "{}:{}/socket.io/1/".format(
                self.host, self.port)

    def _do_handshake(self):
        """ Perform the socket io handshake.

        This function will set the proper variables like heartbeat timeout
        and the sid. It will also make sure that websockets is a valid
        transport for this socket.io server.
        """
        handshake_url = self._get_handshake_url()
        self._logger.debug("Making handshake request to {}".format(
            handshake_url))

        if self._is_version_1():
            handshake = requests.get(handshake_url)
        else:
            handshake = requests.post(handshake_url)

        if handshake.status_code != 200:
            raise Exception("Could not complete handshake: %s" %
                            handshake.text)

        self._logger.debug("Parsing handshake response: {}".format(
            handshake.text))
        if self._is_version_1():
            self._parse_v1_response(handshake.text)
        else:
            self._parse_v0_response(handshake.text)

        self._logger.debug("Handshake successful, sid=%s" % self._sid)

        # Make sure the server reports that they can handle websockets
        if 'websocket' not in self._transports:
            raise Exception("Websocket is not a valid transport for server")

    def _get_handshake_url(self):
        """ Get the URL to perform the initial handshake request to """
        if self._is_version_1():
            return "http://{}?transport=polling".format(self._socket_url_base)

        return "http://{}".format(self._socket_url_base)

    def _parse_v0_response(self, resp_text):
        """ Parse a socket.io v0 handshake response. """
        (self._sid, self._hb_interval, self._hb_timeout,
         self._transports) = resp_text.split(":")

    def _parse_v1_response(self, resp_text):
        """ Parse a socket.io v1 handshake response.

        Expected response should look like:
            \0xxxx {"sid":"xxx", "upgrades":["websocket","polling",..],
            pingInterval:xxxx, pingTimeout:xxxx}
        """
        self._logger.debug("Parsing handshake response: {}".format(resp_text))
        matches = re.search('({.*})', resp_text)

        resp = json.loads(matches.group(1))

        self._sid = resp['sid']
        self._hb_interval = int(resp['pingInterval']) / 1000
        self._hb_timeout = int(resp['pingTimeout']) / 1000
        self._transports = resp['upgrades']

    def _get_ws_url(self):
        """ Get the websocket URL to communciate with """
        if self._is_version_1():
            return "ws://{}?transport=websocket&sid={}".format(
                self._socket_url_base, self._sid)

        return "ws://%swebsocket/%s" % (self._socket_url_base, self._sid)
