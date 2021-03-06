import json
import re
from threading import Event, BoundedSemaphore
import requests

from nio.block.base import Block
from nio.block.mixins.retry.retry import Retry
from nio.command import command
from nio.properties import BoolProperty, IntProperty, StringProperty, \
    Property, VersionProperty, TimeDeltaProperty, SelectProperty
from nio.signal.base import Signal
from nio.signal.status import BlockStatusSignal
from nio.util.runner import RunnerStatus
from nio.util.threading import spawn

from .client.client import SocketIOWebSocketClient

from enum import Enum

class WS_Protocols(Enum):
    ws = "ws"
    wss = "wss"


@command('reconnect_client')
class SocketIO(Retry, Block):

    """ A block for communicating with a socket.io server.

    Properties:
        host (str): location of the socket.io server.
        port (int): socket.io server port.
        room (str): socket.io room.
        content (Expression): Content to send to socket.io room.
        listen (bool): Whether or not the block should listen to messages
            FROM the SocketIo room.

    """
    version = VersionProperty('2.0.0')
    host = StringProperty(title='SocketIo Host', default="127.0.0.1")
    port = IntProperty(title='Port', default=443)
    room = StringProperty(title='Socket.io Room', default="default")
    content = Property(
        title='Content', default="{{ json.dumps($to_dict(), default=str) }}",
        visible=False)
    listen = BoolProperty(title="Listen to SocketIo Room", default=False)
    connect_timeout = TimeDeltaProperty(
        title="Connect timeout",
        default={"seconds": 10},
        visible=False)
    start_without_server = BoolProperty(title="Allow Service Start On Failed "
                                              "Connection", default=False)
    wsp = SelectProperty(WS_Protocols, title="Websocket Protocol", default="ws")

    def __init__(self):
        super().__init__()
        self._sid = ""
        self._hb_interval = -1  # Heartbeat interval
        self._hb_timeout = -1  # Heartbeat timeout
        self._transports = ""  # Valid transports
        self._client = None
        self._client_ready = False
        # This bounded semaphore will ensure that only one thread can be
        # connecting to the client at a time
        self._connection_semaphore = BoundedSemaphore(1)
        self._socket_url_protocol = "http"
        self._socket_url_base = ""
        self._stopping = False
        self._disconnect_thread = None

    def configure(self, context):
        super().configure(context)
        self._build_socket_url_base()
        # Connect to the socket before starting the block
        # This connection won't happen with a retry, so if the socket
        # server is not running, the connection will fail. In this case,
        # if the user has specified that the service should start anyways,
        # attempt to reconnect based off of the given retry strategy.

        try:
            self._connect_to_socket()
        except:
            if self.start_without_server():
                self.logger.info('Could not connect to web socket. Service '
                                 'will be started and this block will attempt '
                                 'to reconnect using given retry strategy.')
                self._disconnect_thread = spawn(self.handle_disconnect)
            else:
                raise

    def stop(self):
        """ Stop the block by closing the client.

        """
        self._stopping = True
        self.logger.debug("Shutting down socket.io client")

        if self._disconnect_thread:
            self._disconnect_thread.join()

        self._close_client()
        super().stop()

    def handle_disconnect(self):
        """ What to do when the client reports a problem """
        # Don't need to reconnect if we are stopping, the close was expected
        if self._stopping:
            return

        try:
            self.logger.info("Attempting to reconnect to the socket")
            self.execute_with_retry(self.reconnect_client)
        except:
            self.logger.exception("Failed to reconnect - giving up")

            status_signal = BlockStatusSignal(
                RunnerStatus.error, 'Out of retries.')
            self.notify_management_signal(status_signal)

    def reconnect_client(self):
        # Only allow one connection at a time by wrapping this call in a
        # bounded semaphore
        self.logger.debug("Acquiring connection semaphore")
        if not self._connection_semaphore.acquire(blocking=False):
            self.logger.warning("Already reconnecting, ignoring request")
            return
        self.logger.debug("Connection semaphore acquired")
        try:
            self._close_client()
            self._connect_to_socket()
        finally:
            self.logger.debug("Releasing connection semaphore")
            self._connection_semaphore.release()

    def handle_data(self, data):
        """Handle data coming from the web socket

        data will be a dictionary, containing an event and data
        that was sent, in the form of a python dictionary.
        """
        if data.get('event', '') != 'recvData':
            # We don't care about this event, it's not data
            return
        try:
            sig = Signal(data['data'])
            self.notify_signals([sig])
        except:
            self.logger.warning("Could not parse socket data", exc_info=True)

    def _connect_to_socket(self):
        connected = Event()
        self._do_handshake()

        url = self._get_ws_url()
        self.logger.info("Connecting to %s" % url)
        self._create_client(url, connected)
        self.logger.info("Connected to socket successfully")

        # Give the client some time to report that it's connected,
        # don't return from this method until that happens
        if not connected.wait(self.connect_timeout().total_seconds()):
            self.logger.warning("Connect response not received in time")
            self._close_client()
            raise Exception("Did not connect in time")
        else:
            self._client_ready = True

    def process_signals(self, signals):
        """ Send content to the socket.io room. """

        # Don't do any processing or sending if the block is stopping.
        # The connection may be closed and we don't want to re-open
        if self._stopping:
            return

        if not self._client or not self._client_ready:
            self.logger.warning(
                "Tried to send to a non-existent or "
                "terminated web socket, dropping signals")
            return

        for signal in signals:
            try:
                message = self.content(signal)
                self._client.sender.send_event('pub', message)
            except:
                self.logger.exception("Could not send message")

    def _close_client(self):
        """ Safely close the client and remove the reference """
        try:
            # The client isn't ready if we're closing
            self._client_ready = False
            # Try to close the client if it's open
            if self._client:
                self._client.close()
        except:
            # If we couldn't close, it's fine. Either the client wasn't
            # opened or it didn't want to respond. That's what we get for
            # being nice and cleaning up our connection
            self.logger.info("Error closing client", exc_info=True)
        finally:
            self._client = None

    def _create_client(self, url, connected_event):
        """ Create a WS client object.

        This will close any existing clients and re-create a client
        object.

        By the time this function returns, the client is connected and
        ready to send data.
        """
        # We will only want to handle incoming data if the block
        # has been configured to do so
        if self.listen():
            data_callback = self.handle_data
        else:
            data_callback = None

        self._client = SocketIOWebSocketClient(
            url=url,
            room=self.room(),
            connect_event=connected_event,
            heartbeat_interval=self._hb_interval,
            heartbeat_timeout=self._hb_timeout,
            data_callback=data_callback,
            disconnect_callback=self.handle_disconnect,
            logger=self.logger)

        self._client.connect()

    def _build_socket_url_base(self):
        host = self.host().strip()
        # Default to http protocol
        # See if they included an http or https in front of the host,
        host_matched = re.match('^(https?)://(.*)$', host)
        if host_matched:
            self._socket_url_protocol = host_matched.group(1)
            host = host_matched.group(2)

        self._socket_url_base = "{}:{}/socket.io/".format(host, self.port())

    def _do_handshake(self):
        """ Perform the socket io handshake.

        This function will set the proper variables like heartbeat timeout
        and the sid. It will also make sure that websockets is a valid
        transport for this socket.io server.
        """
        handshake_url = self._get_handshake_url()
        self.logger.debug("Making handshake request to {}".format(
            handshake_url))

        handshake = requests.get(handshake_url)

        if handshake.status_code != 200:
            raise Exception("Could not complete handshake: %s" %
                            handshake.text)

        self._parse_handshake_response(handshake.text)

        self.logger.debug("Handshake successful, sid=%s" % self._sid)

        # Make sure the server reports that they can handle websockets
        if 'websocket' not in self._transports:
            raise Exception("Websocket is not a valid transport for server")

    def _get_handshake_url(self):
        """ Get the URL to perform the initial handshake request to """
        return "{}://{}?transport=polling".format(
            self._socket_url_protocol, self._socket_url_base)

    def _parse_handshake_response(self, resp_text):
        """ Parse a socket.io v1 handshake response.

        Expected response should look like:
            \0xxxx {"sid":"xxx", "upgrades":["websocket","polling",..],
            pingInterval:xxxx, pingTimeout:xxxx}
        """
        self.logger.debug("Parsing handshake response: {}".format(resp_text))
        matches = re.search('({.*})', resp_text)

        resp = json.loads(matches.group(1))

        self._sid = resp['sid']
        self._hb_interval = int(resp['pingInterval']) / 1000
        self._hb_timeout = int(resp['pingTimeout']) / 1000
        self._transports = resp['upgrades']

    def _get_ws_url(self):
        """ Get the websocket URL to communciate with """
        return "{}://{}?transport=websocket&sid={}".format(self.wsp().value,
            self._socket_url_base, self._sid)
