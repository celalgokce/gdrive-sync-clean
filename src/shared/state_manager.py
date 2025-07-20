import json
import redis
import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class StateManager:
    def __init__(self, redis_host='redis', redis_port=6379, redis_db=0):
        """Redis-based state manager for 12-factor compliance"""
        try:
            self.redis_client = redis.Redis(
                host=redis_host, 
                port=redis_port, 
                db=redis_db,
                decode_responses=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info("Connected to Redis state store")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def get_last_sync_time(self, key: str = 'last_sync_time') -> Optional[str]:
        """Get last sync time from Redis"""
        try:
            sync_time = self.redis_client.get(key)
            if sync_time:
                logger.info(f"Retrieved last sync time: {sync_time}")
                return sync_time
            
            # Default: 10 minutes ago
            default_time = (datetime.utcnow() - 
                          datetime.timedelta(minutes=10)).isoformat() + 'Z'
            logger.info(f"No previous sync time, using default: {default_time}")
            return default_time
            
        except Exception as e:
            logger.error(f"Error getting sync time from Redis: {e}")
            return None

    def set_last_sync_time(self, sync_time: str, key: str = 'last_sync_time') -> bool:
        """Set last sync time in Redis"""
        try:
            self.redis_client.set(key, sync_time)
            logger.info(f"Saved sync time to Redis: {sync_time}")
            return True
        except Exception as e:
            logger.error(f"Error saving sync time to Redis: {e}")
            return False

    def get_state(self, key: str) -> Optional[Dict[Any, Any]]:
        """Get complex state object from Redis"""
        try:
            state_json = self.redis_client.get(key)
            if state_json:
                return json.loads(state_json)
            return None
        except Exception as e:
            logger.error(f"Error getting state {key} from Redis: {e}")
            return None

    def set_state(self, key: str, state: Dict[Any, Any]) -> bool:
        """Set complex state object in Redis"""
        try:
            state_json = json.dumps(state)
            self.redis_client.set(key, state_json)
            logger.info(f"Saved state {key} to Redis")
            return True
        except Exception as e:
            logger.error(f"Error saving state {key} to Redis: {e}")
            return False

    def health_check(self) -> bool:
        """Health check for Redis connection"""
        try:
            return self.redis_client.ping()
        except:
            return False
