#!/usr/bin/env python3
"""
Admin Process Manager
12-Factor compliant admin task runner
"""
import sys
import os
import subprocess
import argparse
from pathlib import Path

ADMIN_PROCESSES = {
    'migrate-state': {
        'script': 'migrate_state.py',
        'description': 'Migrate state from file to Redis'
    },
    'health-check': {
        'script': 'health_check.py', 
        'description': 'Run comprehensive health check'
    },
    'reset-state': {
        'script': 'reset_state.py',
        'description': 'Reset sync state to current time'
    }
}

def list_processes():
    """List available admin processes"""
    print("Available Admin Processes:")
    print("=" * 40)
    for name, info in ADMIN_PROCESSES.items():
        print(f"  {name:<15} - {info['description']}")
    print()

def run_process(process_name, args=None):
    """Run an admin process"""
    if process_name not in ADMIN_PROCESSES:
        print(f"❌ Unknown process: {process_name}")
        return False
    
    script_path = Path(__file__).parent / ADMIN_PROCESSES[process_name]['script']
    
    if not script_path.exists():
        print(f"❌ Script not found: {script_path}")
        return False
    
    cmd = [sys.executable, str(script_path)]
    if args:
        cmd.extend(args)
    
    print(f"🚀 Running: {process_name}")
    print(f"📁 Script: {script_path}")
    print("-" * 40)
    
    try:
        result = subprocess.run(cmd, check=True)
        print("-" * 40)
        print(f"✅ Process {process_name} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print("-" * 40)
        print(f"❌ Process {process_name} failed with exit code {e.returncode}")
        return False

def main():
    parser = argparse.ArgumentParser(description='12-Factor Admin Process Manager')
    parser.add_argument('command', nargs='?', help='Admin process to run')
    parser.add_argument('--list', action='store_true', help='List available processes')
    parser.add_argument('args', nargs='*', help='Arguments to pass to the process')
    
    args = parser.parse_args()
    
    if args.list or not args.command:
        list_processes()
        if not args.command:
            return
    
    if args.command:
        success = run_process(args.command, args.args)
        sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
