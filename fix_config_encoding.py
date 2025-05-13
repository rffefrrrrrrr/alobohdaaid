#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def fix_config_file_encoding(file_path):
    """Fix encoding issues in config files by reading with error handling and rewriting with UTF-8"""
    if not os.path.exists(file_path):
        logger.warning(f"File does not exist: {file_path}")
        return False
    
    # Try to read the file with different encodings
    content = None
    encodings = ['utf-8', 'latin-1', 'cp1256', 'ascii']
    
    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            logger.info(f"Successfully read {file_path} with {encoding} encoding")
            break
        except UnicodeDecodeError:
            logger.debug(f"Failed to read {file_path} with {encoding} encoding")
            continue
    
    if content is None:
        logger.error(f"Could not read {file_path} with any encoding")
        return False
    
    # Write the content back with UTF-8 encoding
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"Successfully rewrote {file_path} with UTF-8 encoding")
        return True
    except Exception as e:
        logger.error(f"Error writing to {file_path}: {e}")
        return False

def main():
    """Fix encoding for config files"""
    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Fix config files
    config_files = [
        os.path.join(current_dir, 'config.py'),
        os.path.join(current_dir, 'config', 'config.py')
    ]
    
    success_count = 0
    for config_file in config_files:
        if os.path.exists(config_file):
            if fix_config_file_encoding(config_file):
                success_count += 1
                print(f"✅ Fixed encoding for {config_file}")
            else:
                print(f"❌ Failed to fix encoding for {config_file}")
    
    if success_count > 0:
        print(f"\nSuccessfully fixed {success_count} config file(s)")
    else:
        print("\nNo config files were fixed")

if __name__ == '__main__':
    main()