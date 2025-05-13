import json
import os
import logging

# Configure logging
logger = logging.getLogger(__name__)

def save_json(data, file_path):
    """
    Save data to a JSON file
    
    Args:
        data: Data to save
        file_path: Path to save file
    
    Returns:
        success (boolean)
    """
    try:
        # Create directory if it doesn't exist
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        
        # Save data to file
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved data to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving data to {file_path}: {str(e)}")
        return False

def load_json(file_path, default=None):
    """
    Load data from a JSON file
    
    Args:
        file_path: Path to load file from
        default: Default value to return if file doesn't exist or is invalid
    
    Returns:
        loaded data or default value
    """
    try:
        # Check if file exists
        if not os.path.exists(file_path):
            logger.warning(f"File {file_path} does not exist")
            return default
        
        # Load data from file
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        logger.info(f"Loaded data from {file_path}")
        return data
    except Exception as e:
        logger.error(f"Error loading data from {file_path}: {str(e)}")
        return default
