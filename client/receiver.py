import json


class PacketReceiver(object):

    def __init__(self, client, logger):
        self._client = client
        self.logger = logger
        self._message_handlers = {
            3: self._recv_heartbeat,
            40: self._recv_connect,
            41: self._recv_disconnect,
            42: self._recv_event
        }

    def handle_message(self, m):
        """ Handle an incoming message from a socket.io server """
        # The message type comes as the first two digits
        try:
            message_type = int(str(m)[:2])
        except ValueError:
            self.logger.warning(
                "Received an improperly formatted message: %s" % m)
            return

        message_data = str(m)[2:]

        self.logger.debug("Received a message: {}".format(message_data))

        # Handle the different types

        if message_type not in self._message_handlers:
            self.logger.warning(
                "Message type %s is not a valid message type" % message_type)
            return

        self._message_handlers[message_type](message_data)

    def _parse_message(self, message):
        """parses a message, if it can"""
        try:
            obj = json.loads(message)
        except ValueError:
            obj = {'message': message}

        return obj

    def _recv_heartbeat(self, data=None):
        self._client._heartbeats.handle_heartbeat_response()

    def _recv_disconnect(self, data=None):
        self.logger.info("Disconnection detected")
        self._client._heartbeats.stop_heartbeats()
        self._disconnect_handler()

    def _recv_connect(self, data=None):
        self.logger.info("Socket.io connection confirmed")

        self.logger.debug("Joining room %s" % self._client._room)
        self._client.sender.send_event('ready', self._client._room)

        # Now that we're connected, start heartbeating
        self._client._heartbeats.start_heartbeats()
        self._client._connect_event.set()

    def _recv_event(self, data=None):
        # when we receive an event, we get a dictionary containing the event
        # name, and a list of arguments that come with it. we only care about
        # the first item in the list of arguments
        if not self._client._listen:
            self.logger.debug("Ignoring incoming data from web socket")
            return

        event_data = json.loads(data)
        self._client._data_handler({
            'event': event_data[0],
            'data': self._parse_message(event_data[1])
        })
