SocketIO
===========

Communicate with a [Socket.IO](http://socket.io/) server. Used to send data to a Socket.IO room and to read data from a Socket.IO room.

Every input signal will be sent to the Socket.IO server *room* and everything sent to that room will be notifed as an output signal.

To send an entire signal, set *content* to `json.dumps(signal.to_dict())`.

Properties
--------------

-   **host**: Socket.IO server location.
-   **port**: Socket.IO server port.
-   **room**: Socket.IO room.
-   **content**: Content to send to room. Should be json encoded.
-   **listen**: whether or not the block should listen to messages from the SocketIo room.
-   **start_without_server**: Allow the service in which this block is running to start even if it is unable to connect to the client initially. The block will then try to reconnect given the retry strategy.


Dependencies
----------------

-   [requests](https://pypi.python.org/pypi/requests/)
-   [ws4py](https://pypi.python.org/pypi/ws4py)

Commands
----------------
-   **reconnect_client**: reconnect to a disconnected client. 

Input
-------
Each input signal is sent as an event to the Socket.IO room.

Output
---------
One signal for every event emitted from the Socket.IO room.
