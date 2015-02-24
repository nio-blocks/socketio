from .socketio_base import SocketIOBase
from .client import SocketIOWebSocketClient
from nio.common.discovery import Discoverable, DiscoverableType
import requests


@Discoverable(DiscoverableType.block)
class SocketIO(SocketIOBase):

    """ A block for communicating with a 0.9.x socket.io server. """

    def _create_client(self, url):
        # In case the client is sticking around, close it before creating a
        # new one
        if self._client:
            self._client.close()

        self._client = SocketIOWebSocketClient(
            url, self._logger, self.room, self.listen,
            self.handle_reconnect, self.handle_data)
        self._client.connect()

    def _build_socket_url_base(self):
        self._socket_url_base = "%s:%s/socket.io/1/" % (self.host, self.port)

    def _do_handshake(self):
        handshake = requests.post("http://" + self._socket_url_base)

        if handshake.status_code != 200:
            raise Exception("Could not complete handshake: %s" %
                            handshake.text)

        self._logger.debug("Parsing handshake response: {}".format(
            handshake.text))

        # Assign the properties of the socket server
        (self._sid, self._hb_interval, self._hb_timeout,
         self._transports) = handshake.text.split(":")

        self._logger.debug("Handshake successful, sid=%s" % self._sid)

        # Make sure the server reports that they can handle websockets
        if 'websocket' not in self._transports:
            raise Exception("Websocket is not a valid transport for server")

    def _get_ws_url(self):
        return "ws://%swebsocket/%s" % (self._socket_url_base, self._sid)
