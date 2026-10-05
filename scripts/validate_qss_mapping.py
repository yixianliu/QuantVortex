#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate QSS token mapping in design_system.py.
Ensures all $TOKEN$ placeholders in _QSS_TEMPLATE have a corresponding entry in build_qss mapping.
Also reports any mapping entries that are not used in the template (potentially obsolete).
"""

import re
import sys
from pathlib import Path

def extract_template_tokens(template: str) -> set[str]:
    """Return set of token placeholders like $TOKEN$ found in template."""
    pattern = r'\$[A-Za-z0-9_]+\$'
    return set(re.findall(pattern, template))

def extract_mapping_tokens(content: str) -> set[str]:
    """Extract token keys from the mapping dict in build_qss function."""
    lines = content.splitlines()
    in_mapping = False
    tokens = set()
    for line in lines:
        if 'mapping = {' in line:
            in_mapping = True
            continue
        if in_mapping:
            if '}' in line:
                break
            # Find all quoted $TOKEN$ patterns in the line
            found = re.findall(r'"(\$[A-Za-z0-9_]+\$)"', line)
            tokens.update(found)
    return tokens

def main():
    design_system_path = Path(r'D:\PythonProject\QuantVortex\futures_quant\ui\design_system.py')
    if not design_system_path.is_file():
        print(f"Error: {design_system_path} not found", file=sys.stderr)
        sys.exit(1)
    
    content = design_system_path.read_text(encoding='utf-8')
    
    # extract _QSS_TEMPLATE
    template_match = re.search(r'_QSS_TEMPLATE\s*=\s*"""([\s\S]*?)"""', content, re.DOTALL)
    if not template_match:
        print("Error: _QSS_TEMPLATE not found", file=sys.stderr)
        sys.exit(1)
    template = template_match.group(1)
    
    template_tokens = extract_template_tokens(template)
    mapping_tokens = extract_mapping_tokens(content)
    
    missing_in_mapping = template_tokens - mapping_tokens
    extra_in_mapping = mapping_tokens - template_tokens
    
    print(f"Template tokens count: {len(template_tokens)}")
    print(f"Mapping tokens count: {len(mapping_tokens)}")
    print()
    if missing_in_mapping:
        print("Missing in mapping (need to add):")
        for tok in sorted(missing_in_mapping):
            print(f"  {tok}")
        print()
        # Suggest additions
        print("Suggested mapping additions:")
        for tok in sorted(missing_in_mapping):
            var = tok[1:-1]  # strip $ 
            print(f'        "{tok}": str(tk["{var}"]),')
    else:
        print("✅ All template tokens have mapping entries.")
    print()
    if extra_in_mapping:
        print("⚠️  Extra mapping entries not used in template (may be intentional for future use):")
        for tok in sorted(extra_in_mapping):
            print(f"  {tok}")
    else:
        print("✅ No extra mapping entries.")
    print()
    
    # Determine exit code: 0 if no missing, else 1
    return 0 if not missing_in_mapping else 1

if __name__ == '__main__':
    sys.exit(main())