import json
from ws4py.client import WebSocketBaseClient
from nio.modules.threading import Thread


class SocketIOWebSocketClient(WebSocketBaseClient):

    def __init__(self, url, block):
        super().__init__(url, None, None)
        self._th = Thread(target=self.run, name='SocketIOWebSocketClient')
        self._block = block
        self._logger = block._logger
        self._room = block.room
        self._listen = block.listen
        self._restart_handler = block.handle_reconnect
        self._data_handler = block.handle_data

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
        self._logger.info("Disconnection detected")
        self._restart_handler()

    def received_message(self, m):
        message_parts = str(m).split(":")

        if len(message_parts) < 3:
            self._logger.warning(
                "Received an improperly formatted message: %s" % m)
            return

        self._logger.debug("Received a message: {}".format(message_parts))

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

        msg_type = int(message_type)
        if msg_type in range(3, 6) and not self._listen:
            self._logger.debug("Ignoring incoming data from web socket")
        elif msg_type not in message_handlers:
            self._logger.warning(
                "Message type %s is not a valid message type" % message_type)
        else:
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
