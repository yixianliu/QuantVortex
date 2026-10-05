#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automatically update the QSS token mapping in design_system.py's build_qss function.
Extracts all $TOKEN$ placeholders from _QSS_TEMPLATE and generates the corresponding mapping.
"""

import re
import sys
from pathlib import Path

def extract_tokens_from_template(template: str) -> list[str]:
    """Extract all token placeholders like $TOKEN$ from template, preserving order of first appearance."""
    pattern = r'\$[A-Z0-9_]+\$'
    tokens = re.findall(pattern, template)
    # Remove duplicates while preserving order
    seen = set()
    unique_tokens = []
    for token in tokens:
        if token not in seen:
            seen.add(token)
            unique_tokens.append(token)
    return unique_tokens

def generate_mapping_lines(tokens: list[str]) -> str:
    """Generate the mapping dictionary lines for build_qss."""
    lines = []
    for token in tokens:
        # Convert $TOKEN$ to tk["token"] variable name
        var_name = token[1:-1]  # Remove the $ at start and end
        lines.append(f'        "{token}": str(tk["{var_name}"]),')
    return '\n'.join(lines)

def update_build_qss_mapping(file_path: Path) -> bool:
    """Update the mapping in build_qss function with tokens from _QSS_TEMPLATE."""
    try:
        content = file_path.read_text(encoding='utf-8')
        
        # Extract _QSS_TEMPLATE
        template_match = re.search(r'_QSS_TEMPLATE\s*=\s*"""([\s\S]*?)"""', content, re.DOTALL)
        if not template_match:
            print("Error: _QSS_TEMPLATE not found", file=sys.stderr)
            return False
        template = template_match.group(1)
        
        # Extract tokens from template
        tokens = extract_tokens_from_template(template)
        
        # Generate new mapping lines
        new_mapping = generate_mapping_lines(tokens)
        
        # Replace the mapping in build_qss function
        # Find the build_qss function and its mapping
        lines = content.splitlines()
        in_build_qss = False
        in_mapping = False
        mapping_start = -1
        mapping_end = -1
        
        for i, line in enumerate(lines):
            if 'def build_qss(' in line:
                in_build_qss = True
                continue
            if in_build_qss and 'mapping = {' in line:
                in_mapping = True
                mapping_start = i
                continue
            if in_mapping and '}' in line and mapping_start != -1:
                # Check if this is the closing brace of the mapping
                # (assuming it's at the same indentation level as "mapping = {")
                if line.strip() == '}':
                    mapping_end = i
                    break
        
        if mapping_start == -1 or mapping_end == -1:
            print("Error: Could not locate mapping in build_qss function", file=sys.stderr)
            return False
        
        # Construct new content
        new_lines = (
            lines[:mapping_start + 1] +  # Keep everything up to and including "mapping = {"
            [new_mapping] +              # Replace the mapping content
            lines[mapping_end:]          # Keep from the closing brace onwards
        )
        
        new_content = '\n'.join(new_lines)
        
        # Write back to file
        file_path.write_text(new_content, encoding='utf-8')
        
        print(f"✅ Successfully updated build_qss mapping with {len(tokens)} tokens")
        print(f"   Tokens processed: {', '.join(tokens)}")
        return True
        
    except Exception as e:
        print(f"Error updating mapping: {e}", file=sys.stderr)
        return False

def main():
    design_system_path = Path(r'D:\PythonProject\QuantVortex\futures_quant\ui\design_system.py')
    if not design_system_path.is_file():
        print(f"Error: {design_system_path} not found", file=sys.stderr)
        sys.exit(1)
    
    if update_build_qss_mapping(design_system_path):
        print("🎉 Mapping update completed successfully.")
        # Validate the update
        from scripts.validate_qss_mapping import main as validate_main
        if validate_main() == 0:
            print("✅ Validation passed: all template tokens have mapping entries.")
        else:
            print("⚠️  Validation failed: there may be issues with the mapping.")
            sys.exit(1)
    else:
        print("💥 Failed to update mapping.")
        sys.exit(1)

if __name__ == '__main__':
    main()