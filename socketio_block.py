from nio.common.block.base import Block
from nio.common.discovery import Discoverable, DiscoverableType
from nio.metadata.properties.int import IntProperty
from nio.metadata.properties.string import StringProperty
from nio.metadata.properties.expression import ExpressionProperty
from nio.modules.scheduler import Job
from nio.common.signal.base import Signal
from nio.modules.threading import Lock, Thread

from datetime import timedelta
import json
import requests

from ws4py.client import WebSocketBaseClient


class SocketIOWebSocketClient(WebSocketBaseClient):

    def __init__(self, url, logger, room, restart_handler, data_handler):
        super(SocketIOWebSocketClient, self).__init__(url, None, None)
        self._th = Thread(target=self.run, name='SocketIOWebSocketClient')
        self._logger = logger
        self._room = room
        self._restart_handler = restart_handler
        self._data_handler = data_handler

    def handshake_ok(self):
        self._th.start()
        self._th.join(timeout=1.0)

    def opened(self):
        self._logger.info("Socket connection open")

    def closed(self, code, reason=None):
        self._logger.info(
            "Socket connection closed {0}:{1}".format(code, reason))
        self.handle_disconnect()

    def handle_disconnect(self):
        self._logger.debug("Disconnection detected")
        self._restart_handler()

    def received_message(self, m):
        message_parts = str(m).split(":")

        if len(message_parts) < 3:
            self._logger.warning(
                "Received an improperly formatted message: %s" % m)
            return

        # Message data can come in an optional 4th section, it may have colons,
        # so join the rest of it together
        if len(message_parts) >= 4:
            message_data = ":".join(message_parts[3:])
        else:
            message_data = ""

        # Extract message information
        (message_type, message_id, message_endpoint) = message_parts[:3]

        # Handle the different types
        message_handlers = {
            0: self._recv_disconnect,
            1: self._recv_connect,
            2: self._recv_heartbeat,
            3: self._recv_msg,
            4: self._recv_json,
            5: self._recv_event,
            6: self._recv_ack,
            7: self._recv_error,
            8: self._recv_noop
        }

        if int(message_type) not in message_handlers:
            self._logger.warning(
                "Message type %s is not a valid message type" % message_type)
            return

        message_handlers[int(message_type)](message_data)

    def send_msg(self, msg):
        self._send_packet(3, '', '', msg)

    def send_dict(self, data):
        self._send_packet(4, '', '', json.dumps(data))

    def send_event(self, event, data):
        event_details = {
            "name": event,
            "args": data
        }
        self._send_packet(5, '', json.dumps(event_details))

    def _send_packet(self, code, path='', data='', id=''):
        packet_text = ":".join([str(code), id, path, data])
        self._logger.debug("Sending packet: %s" % packet_text)
        try:
            self.send(packet_text)
        except Exception as e:
            self._logger.error(
                "Error sending packet: {0}: {1}".format(type(e).__name__,
                                                        str(e))
            )

    def _send_heartbeat(self):
        self._logger.debug("Sending heartbeat message")
        self._send_packet(2)

    def _parse_message(self, message):
        """parses a message, if it can"""
        try:
            obj = json.loads(message)
        except Exception:
            obj = {'message': message}

        return obj

    def _recv_disconnect(self, data=None):
        self.handle_disconnect()

    def _recv_connect(self, data=None):
        self._logger.info("Socket.io connection confirmed")

        self._logger.debug("Joining room %s" % self._room)
        self.send_event('ready', self._room)

    def _recv_heartbeat(self, data=None):
        # When we get a heartbeat from the server, send one back!
        self._send_heartbeat()

    def _recv_msg(self, data=None):
        self._data_handler(self._parse_message(data))

    def _recv_json(self, data=None):
        self._data_handler(self._parse_message(data))

    def _recv_event(self, data=None):
        # when we receive an event, we get a dictionary containing the event
        # name, and a list of arguments that come with it. we only care about
        # the first item in the list of arguments
        event_data = json.loads(data)
        self._data_handler({
            'event': event_data['name'],
            'data': self._parse_message(event_data['args'][0])
        })

    def _recv_ack(self, data=None):
        pass

    def _recv_error(self, data=None):
        pass

    def _recv_noop(self, data=None):
        pass


@Discoverable(DiscoverableType.block)
class SocketIO(Block):

    """ A block for communicating with a socket.io server.

    Properties:
        host (str): location of the socket.io server.
        port (int): socket.io server port.
        room (str): socket.io room.
        content (Expression): Content to send to socket.io room.

    """
    host = StringProperty(title='SocketIo Hose', default="127.0.0.1")
    port = IntProperty(title='Port', default=443)
    room = StringProperty(title='SocketIo Room', default="default")
    content = ExpressionProperty(title='Content',
                                 default="{{json.dumps($to_dict(), default=str)}}")

    def __init__(self):
        super().__init__()
        self._sid = ""
        self._hb_timeout = -1  # Heartbeat timeout
        self._close_timeout = -1  # Close connection timeout
        self._transports = ""  # Valid transports
        self._client = None
        self._socket_url_base = ""
        self._timeout = 1

    def configure(self, context):
        super().configure(context)
        self._socket_url_base = "%s:%s/socket.io/1/" % (self.host, self.port)

    def start(self):
        """ Start the block by connecting to socket server.

        """
        super().start()
        self._logger.debug("Starting socket.io client")
        self._connect_to_socket()

    def stop(self):
        """ Stop the block by closing the client.

        """
        super().stop()
        self._logger.debug("Shutting down socket.io client")
        self._client.close()

    def handle_reconnect(self):
        self._timeout = self._timeout or 1
        self._client = None
        self._logger.debug("Attempting to reconnect in {0} seconds."
                           .format(self._timeout))
        if self._timeout <= 64:
            self._logger.debug("Attempting to reconnect")
            Job(
                self._connect_to_socket,
                timedelta(seconds=self._timeout),
                repeatable=False
            )
        else:
            self._logger.error(
                "Failed to reconnect after unexpected close. Giving up."
            )

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
            self._do_handshake()

            url = self._get_ws_url()

            self._logger.debug("Connecting to %s" % url)

            self._client = SocketIOWebSocketClient(
                url, self._logger, self.room,
                self.handle_reconnect, self.handle_data)
            self._client.connect()

            # Reset the timeout
            self._timeout = 1

            self._logger.info("Connected to socket successfully")
        except Exception as e:
            self._timeout *= 2
            self._logger.error(e)
            self.handle_reconnect()

    def _do_handshake(self):
        handshake = requests.post("http://" + self._socket_url_base)

        if handshake.status_code != 200:
            raise Exception("Could not complete handshake: %s" %
                            handshake.text)

        # Assign the properties of the socket server
        (self._sid, self._hb_timeout, self._close_timeout,
         self._transports) = handshake.text.split(":")

        self._logger.debug("Handshake successful, sid=%s" % self._sid)

        # Make sure the server reports that they can handle websockets
        if 'websocket' not in self._transports:
            raise Exception("Websocket is not a valid transport for server")

    def _get_ws_url(self):
        return "ws://%swebsocket/%s" % (self._socket_url_base, self._sid)

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
