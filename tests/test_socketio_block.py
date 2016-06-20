from time import sleep
import json
from ..socketio_block import SocketIO, SocketIOWebSocketClient
from nio.util.support.block_test_case import NIOBlockTestCase
from nio.common.signal.base import Signal
from nio.modules.threading import spawn
from unittest.mock import MagicMock, patch


class MsgSignal(Signal):

    def __init__(self, message):
        super().__init__()
        self.message = message


@patch.object(SocketIOWebSocketClient, 'send_event')
@patch.object(SocketIOWebSocketClient, 'connect')
@patch.object(SocketIOWebSocketClient, 'close')
class TestSocketIO(NIOBlockTestCase):

    def setUp(self):
        super().setUp()
        self._block = SocketIO()
        self._block._do_handshake = MagicMock()

    def test_send(self, socket_close, socket_connect, socket_send_event):
        """Test that the block can send a signal."""
        message = 'hello_nio'
        self.configure_block(self._block, {
            'socketio_version': 'v0',
            'content': "{{$message}}",
            'log_level': 'DEBUG'
        })
        self._block.start()
        self._block.process_signals([MsgSignal(message)])

        socket_send_event.assert_called_once_with('pub', message)

        self._block.stop()

    def test_bogus_content_expr(self, socket_close, socket_connect,
                                socket_send_event):
        self.configure_block(self._block, {
            'socketio_version': 'v0',
            'content': '{{dict($message)}}',
            'log_level': 'DEBUG'
        })
        self._block.start()

        signals = [Signal({'message': 'foobar'})]
        self._block.process_signals(signals)

        self.assertFalse(socket_send_event.called)

    def test_default_expression(self, socket_close, socket_connect,
                                socket_send_event):
        self.configure_block(self._block, {
            'socketio_version': 'v0'
        })
        self._block.start()

        signal = Signal({'message': 'foobar'})
        self._block.process_signals([signal])
        socket_send_event.assert_called_with('pub',
                                             json.dumps(signal.to_dict(),
                                                        default=str))

    def test_management_signal(self, socket_close, socket_connect,
                               socket_send_event):
        """ Test that on failed connections the block notifies mgmt sigs """

        # Our connect method should raise an exception
        socket_connect.side_effect = [True, Exception, Exception, Exception]
        self._block.notify_management_signal = MagicMock()

        # We want to not retry more than 2 seconds
        self.configure_block(self._block, {
            'socketio_version': 'v0',
            'content': '',
            'log_level': 'DEBUG',
            'retry_options': {'max_retry': 1}
        })
        self._block.start()
        # Force a reconnection
        self._block.handle_reconnect()
        # Should have an initial connection, a failed reconnect, then a retry
        self.assertEqual(socket_connect.call_count, 3)
        self.assertTrue(self._block.notify_management_signal.called)

    def test_no_send_after_stop(self, close, conn, send):
        """ Make sure signals sent after stop aren't sent """
        self.configure_block(self._block, {
            'socketio_version': 'v0'
        })

        # We expect one call to send when the block is started
        self._block.start()
        self._block.process_signals([Signal()])
        self.assertEqual(send.call_count, 1)

        # Now let's stop the block and make sure send didn't get called again
        # even if we send signals afterwards
        self._block.stop()
        self._block.process_signals([Signal()])
        self.assertEqual(send.call_count, 1)

    def test_simultaneous_reconnects(self, close, conn, send):
        """ Tests that only one reconnect occurs at a time """
        def sleep_a_while():
            sleep(1)
        # We will simulate our "connecting" by sleeping for a bit
        with patch.object(self._block, '_connect_to_socket',
                          side_effect=sleep_a_while) as client_mock:
            # In case multiple threads try to handle a reconnection, we
            # want to make sure that the reconnect is only handled once
            spawn(self._block.handle_reconnect)
            spawn(self._block.handle_reconnect)

            # Give the handlers some time to happen (we are sleeping instead
            # of connecting)
            sleep(2)
            self.assertEqual(client_mock.call_count, 1)

    def test_force_simultaneous_reconnects(self, close, conn, send):
        """ Tests that we can force a simultaneous reconnect """
        def sleep_a_while():
            sleep(1)
        # We will simulate our "connecting" by sleeping for a bit
        with patch.object(self._block, '_connect_to_socket',
                          side_effect=sleep_a_while) as client_mock:
            # In case multiple threads try to handle a reconnection, we
            # want the second reconnect attempt to force the reconnection
            # to happen, even though another one is already happening
            spawn(self._block.handle_reconnect, force_reconnect=True)
            spawn(self._block.handle_reconnect, force_reconnect=True)

            # Give the handlers some time to happen (we are sleeping instead
            # of connecting)
            sleep(2)
            # This time we want to make sure it was called twice
            self.assertEqual(client_mock.call_count, 2)

    def test_subsequent_reconnects(self, close, conn, send):
        """ Tests that the reconnect handler can be called multiple times """
        self._block.notify_management_signal = MagicMock()

        def sleep_a_while():
            sleep(0.5)
        # We will simulate our "connecting" by sleeping for a bit
        with patch.object(self._block, '_connect_to_socket',
                          side_effect=sleep_a_while) as client_mock:
            # Configure the block inside of the patch, this will cause
            # our connection method to be called once, that is ok.
            self.configure_block(self._block, {})

            # In this example, we want a different thread to issue the
            # reconnect but then succeed. Then, we'll make sure another thread
            # can call reconnect again and it will work (i.e. it won't
            # continue to block the other thread if the previous reconnect
            # is done)
            spawn(self._block.handle_reconnect)
            # Give reconnect attempt number 1 time to finish
            sleep(1)
            spawn(self._block.handle_reconnect)
            # Give reconnect attempt number 2 time to finish
            sleep(1)
            # We should have tried connecting twice for reconnects and once
            # for the initial configuration of the block
            self.assertEqual(client_mock.call_count, 3)

        # Make sure the block did not enter error state
        self.assertFalse(self._block.notify_management_signal.called)
