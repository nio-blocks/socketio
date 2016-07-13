import json


class PacketSender(object):

    def __init__(self, client, logger):
        super().__init__()
        self._client = client
        self.logger = logger

    def send_msg(self, msg):
        self.send_packet(3, '', '', msg)

    def send_dict(self, data):
        self.send_packet(4, '', '', json.dumps(data))

    def send_event(self, event, data):
        self.send_packet(42, event, data)

    def send_heartbeat(self):
        self.logger.debug("Sending heartbeat message")
        self.send_packet(2)

    def send_packet(self, code, path='', data='', id=''):
        if path or data:
            packet_text = "{}{}".format(code, json.dumps([path, data]))
        else:
            packet_text = "{}".format(code)

        self.logger.debug("Sending packet: %s" % packet_text)
        try:
            self.send(packet_text)
        except:
            self.logger.exception("Error sending packet")
