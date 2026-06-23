# Automation module for cloud storage and messaging integrations
import sys
import os

# Auto-add parent directory (src) to sys.path to allow imports from 'automation.*'
src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
