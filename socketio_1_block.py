import requests
import json
import re
from .socketio_base import SocketIOBase
from .client_1 import SocketIOWebSocketClientV1
from nio.common.discovery import Discoverable, DiscoverableType


@Discoverable(DiscoverableType.block)
class SocketIO1x(SocketIOBase):

    """ A block for communicating with a 1.x.x socket.io server. """

    def _create_client(self, url):
        # In case the client is sticking around, close it before creating a
        # new one
        if self._client:
            self._client.close()

        self._client = SocketIOWebSocketClientV1(
            url, self._logger, self.room, self.listen,
            self.handle_reconnect, self.handle_data)
        self._client.connect()

    def _build_socket_url_base(self):
        self._socket_url_base = "{}:{}/socket.io/?EIO=3".format(
            self.host, self.port)

    def _do_handshake(self):
        handshake_url = "http://{}&transport=polling".format(
            self._socket_url_base)

        self._logger.debug("Making handshake request to {}".format(
            handshake_url))

        handshake = requests.get(handshake_url)

        if handshake.status_code != 200:
            raise Exception("Could not complete handshake: %s" %
                            handshake.text)

        self._parse_response(handshake.text)

        self._logger.debug("Handshake successful, sid=%s" % self._sid)

        # Make sure the server reports that they can handle websockets
        if 'websocket' not in self._transports:
            raise Exception("Websocket is not a valid transport for server")

    def _parse_response(self, resp_text):
        matches = re.search('({.*})', resp_text)

        resp = json.loads(matches.group(1))

        self._sid = resp['sid']
        self._hb_timeout = resp['pingInterval']
        self._close_timeout = resp['pingTimeout']
        self._transports = resp['upgrades']

    def _get_ws_url(self):
        return "ws://{}&transport=websocket&sid={}".format(
            self._socket_url_base, self._sid)
