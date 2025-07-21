import signal
import sys
import logging
import threading
import time
from typing import Callable, List

logger = logging.getLogger(__name__)

class GracefulShutdownHandler:
    """12-Factor compliant graceful shutdown handler"""
    
    def __init__(self, shutdown_timeout: int = 30):
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_callbacks: List[Callable] = []
        self.is_shutting_down = False
        self.shutdown_event = threading.Event()
        
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
        logger.info(f"Graceful shutdown handler initialized (timeout: {shutdown_timeout}s)")
    
    def add_shutdown_callback(self, callback: Callable):
        """Add a function to call during shutdown"""
        self.shutdown_callbacks.append(callback)
        logger.debug(f"Added shutdown callback: {callback.__name__}")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name} signal, initiating graceful shutdown...")
        
        if self.is_shutting_down:
            logger.warning("Already shutting down, forcing exit")
            sys.exit(1)
        
        self.is_shutting_down = True
        self.shutdown_event.set()
        
        # Execute shutdown callbacks
        self._execute_shutdown_callbacks()
        
        # Exit cleanly
        logger.info("Graceful shutdown completed")
        sys.exit(0)
    
    def _execute_shutdown_callbacks(self):
        """Execute all shutdown callbacks with timeout"""
        start_time = time.time()
        
        for callback in self.shutdown_callbacks:
            try:
                remaining_time = self.shutdown_timeout - (time.time() - start_time)
                if remaining_time <= 0:
                    logger.warning("Shutdown timeout reached, forcing exit")
                    break
                
                logger.info(f"Executing shutdown callback: {callback.__name__}")
                callback()
                
            except Exception as e:
                logger.error(f"Error in shutdown callback {callback.__name__}: {e}")
    
    def wait_for_shutdown(self):
        """Block until shutdown signal received"""
        self.shutdown_event.wait()
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested"""
        return self.is_shutting_down
