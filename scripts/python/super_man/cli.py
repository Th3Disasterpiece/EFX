#!/usr/bin/env python3
import argparse
from managers.setup_man.installer import SetupManager

def main():
    parser = argparse.ArgumentParser(description="SuperMan Management System")
    subparsers = parser.add_subparsers(dest='command')
    
    # Setup command
    setup_parser = subparsers.add_parser('setup', help='Installation management')
    setup_parser.add_argument('action', choices=['install', 'update'])
    
    args = parser.parse_args()
    
    if args.command == 'setup':
        manager = SetupManager()
        manager.execute(args.action)

if __name__ == '__main__':
    main()
