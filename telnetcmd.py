"""Host cmd.Cmd subclasses over a TELNET connection.

Example usage:
Say you have a subclass of cmd.Cmd that you want multiple users to access simultaneously, perhaps interacting with each other.
Using a single terminal for this purpose is nigh impossible and gets complicated fast.  Telnet clients are available for nearly
every platform in existence.  Python does not have a built-in module to host a Telnet server, unless you count
socketserver.TCPHanlder, which cannot process Telnet options.  telnetcmd.TelnetCmd inherits from telnetlib.Telnet, so  you can
use set_option_negotiation_callback() (see telnetcmd2 (which is as of yet a work in progress) for automatic handling of options
according to various RFCs).  

Have your cmd.Cmd subclass(es) subclass telnetcmd.TelnetCmd instead, or write something along the lines of
`class MyRemoteCmd(telnetcmd.TelnetCmd, MyCmd): pass`, then call the serve_forever() class method from your __main__.

Important safety tip: if you don't specify file=self.stdout to a print() call, your output will go to the server console rather
than the client.

telnetcmd.TelnetCmd subclasses can still be instantiated normally, so there is nothing wrong with the statement
MyRemoteCmd().cmdloop()
"""

import telnetlib
from telnetlib import IAC
import socketserver
import cmd
import io

class _TelnetReader(io.BufferedReader):
  def __init__(self, telnet, before_read):
    self.telnet=telnet
    super().__init__(telnet.get_socket().makefile('rb', buffering=0))
  
  def readable(self):
    return True
  
  def read(self, n=-1):
    if n==-1:
      return self.telnet.read_all()
    self.telnet.process_rawq()
    while not self.telnet.eof and len(self.telnet.cookedq)<n:
      self.telnet.fill_rawq()
      self.telnet.process_rawq()
    # remove the specified number of bytes from the queue and return them
    buf, self.telnet.cookedq=self.telnet.cookedq[:n], self.telnet.cookedq[n:]
    return buf
  
  def read1(self, n=-1):
    if n==-1:
      return self.telnet.read_lazy()
    self.telnet.process_rawq()
    if not self.telnet.eof and len(self.telnet.cookedq)<n:
      self.telnet.fill_rawq()
      self.telnet.process_rawq()
    buf, self.telnet.cookedq=self.telnet.cookedq[:n], self.telnet.cookedq[n:]
    return buf
  
  def peek(self, n=-1, *, process_rawq=True):
    """Return up to n bytes from the Telnet object's cooked data queue without removing them from the queue.
    
    If the optional argument process_rawq is True (the default), the raw queue is scanned for IAC sequences
    (which may block if the raw queue ends in the middle of one).
    """
    if process_rawq:
      self.telnet.process_rawq() # XXX is this necessary / should it be done?
    
    if n is None or n<0:
      return self.telnet.cookedq
    else:
      return self.telnet.cookedq[:n]
  
  def fileno(self):
    return self.telnet.get_socket().fileno()
  
#  @property
#  def raw(self):
#    return self.telnet.get_socket()
#  
#  def detach(self):
#    socket=self.telnet.get_socket()
#    self.telnet=None
#    return socket


class _TelnetWriter(io.BufferedWriter):
  """Thin wrapper around io.BufferedWriter that doubles IAC characters in calls to write()."""
  def __init__(self, telnet):
    """telnet should be a telnetlib.Telnet object (TelnetRequestHandler subclasses telnetlib.Telnet).
    """
    super().__init__(telnet.get_socket().makefile('wb', buffering=0))
  
  def write(self, data):
    # XXX should maybe modify the return value to account for the IAC characters that were doubled?
    data=data.replace(IAC, IAC+IAC) # double IAC characters as per telnet spec
    return super().write(data)


class TelnetRequestHandler(socketserver.BaseRequestHandler, telnetlib.Telnet):
  """Define self.rfile and self.wfile for an RFC 854-compliant TELNET connection."""
  def setup(self):
    super().setup()
    telnetlib.Telnet.__init__(self)
    self.sock = self.request  # so that telnetlib (and maybe the user) can see it
    self.rfile = _TelnetReader(self)
    self.wfile = _TelnetWriter(self)


class TelnetCmd(cmd.Cmd, TelnetRequestHandler):
  def handle(self):
    super().__init__(stdin=io.TextIOWrapper(self.rfile), stdout=io.TextIOWrapper(self.wfile))
    # XXX `class MyRemoteProcessor(TelnetCmd, MyCmdProcessor): pass` is perfectly legal and we should be able to handle it
    self.use_rawinput=False
    self.cmdloop()
  
  @classmethod
  def serve_forever(cls, port=telnetlib.TELNET_PORT, ServerClass=socketserver.ThreadingTCPServer, poll_interval=0.5):
    """Convenience method that starts a server listening on the specified port.  Clients will each be assigned an instance of the
    invoking class, by default in their own thread.
    
    This will block until the server is shut down, so reccommended usage is to start it in another thread, or as the last
    statement in __main__.
    
    The port argument defaults to 23.  On Windows this will not cause any problems, but for compatibility for Unix I reccommend
    specifying another port.
    """
    with ServerClass(('', port), cls.handle_request) as server:
      server.serve_forever(poll_interval)
  
  @classmethod
  def handle_request(cls, request, client_address, server):
    """Invoked by socketserver when a client connects.
    Pass this method as the RequestHandlerClass argument to socketserver.TCPServer (or some subclass thereof).
    
    This creates a new instance and calls TelnetRequestHandler.__init__(), which takes care of everything.
    Returns self for good mesasure, even though this is usually unneccessary as this method does not return
    until cmd.Cmd.cmdloop() does.
    """
    self=super().__new__(cls)
    TelnetRequestHandler.__init__(self, request, client_address, server)
    return self
