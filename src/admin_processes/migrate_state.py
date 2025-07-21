#!/usr/bin/env python3
"""
Admin Process: Migrate state from file to Redis
12-Factor compliant one-off process
"""
import sys
import os
import json
import logging
from pathlib import Path

# Add shared directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../shared')))

from config import get_config
from state_manager import StateManager

def migrate_file_state_to_redis():
    """Migrate state from sync_state.json to Redis"""
    config = get_config()
    
    # Initialize state manager
    try:
        state_manager = StateManager()
        print("✅ Connected to Redis")
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False
    
    # Check if file exists
    state_file = config.SYNC_STATE_FILE
    if not state_file.exists():
        print(f"⚠️  State file not found: {state_file}")
        return True
    
    try:
        # Read file state
        with open(state_file, 'r') as f:
            file_state = json.load(f)
        
        print(f"📁 Found state file with {len(file_state)} keys")
        
        # Migrate each key
        migrated_keys = 0
        for key, value in file_state.items():
            if isinstance(value, dict):
                state_manager.set_state(key, value)
            else:
                state_manager.set_last_sync_time(value, key)
            
            migrated_keys += 1
            print(f"   ✅ Migrated: {key}")
        
        print(f"🎯 Migration completed: {migrated_keys} keys migrated to Redis")
        
        # Backup original file
        backup_file = state_file.with_suffix('.backup.json')
        state_file.rename(backup_file)
        print(f"📦 Original file backed up to: {backup_file}")
        
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

if __name__ == '__main__':
    print("🔄 Starting state migration (File → Redis)")
    print("=" * 50)
    
    success = migrate_file_state_to_redis()
    
    if success:
        print("=" * 50)
        print("🎉 Migration completed successfully!")
        sys.exit(0)
    else:
        print("=" * 50)
        print("💥 Migration failed!")
        sys.exit(1)
