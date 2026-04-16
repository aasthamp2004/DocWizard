#!/usr/bin/env python3
"""
Generate a PNG visualization of the langgraph from backend/services/p3/graph.py
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from backend.services.p3.for_graph import get_graph
    print("✓ Successfully imported the graph")
    
    # Get the compiled graph
    graph = get_graph()
    print("✓ Successfully retrieved compiled graph")
    
    # Generate PNG visualization using langgraph's draw method
    output_path = os.path.join(os.path.dirname(__file__), "graph_visualization.png")
    
    try:
        # Try using the draw method (requires Pillow)
        png_data = graph.get_graph().draw_mermaid_png()
        with open(output_path, "wb") as f:
            f.write(png_data)
        print(f"✓ Successfully generated PNG: {output_path}")
    except Exception as e:
        print(f"Note: draw_mermaid_png() not available ({e})")
        print("Trying alternative visualization method...")
        
        # Fallback: generate Mermaid diagram and save as text
        try:
            mermaid_diagram = graph.get_graph().draw_mermaid()
            mermaid_path = output_path.replace(".png", ".mmd")
            with open(mermaid_path, "w") as f:
                f.write(mermaid_diagram)
            print(f"✓ Successfully generated Mermaid diagram: {mermaid_path}")
            print("\nYou can convert this to PNG using:")
            print(f"  mmdc -i {mermaid_path} -o {output_path}")
        except Exception as e2:
            print(f"Fallback method also failed: {e2}")
            raise

except ImportError as e:
    print(f"✗ Failed to import graph: {e}")
    print("\nMake sure the project dependencies are installed:")
    print("  pip install -r requirements.txt")
    sys.exit(1)
except Exception as e:
    print(f"✗ Error during visualization: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
