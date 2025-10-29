# CoffeeBoard
Nuke panel, inspired by PureRef, for managing and displaying reference images directly within Nuke.

CoffeeBoard is a Python-based tool designed to empower compositors by allowing them to quickly drag, drop, and view reference images within a floating Nuke panel, significantly streamlining the compositing workflow.

## 🛠️ Installation

This project is intended to be added as a plugin within your personal Nuke environment (typically the `~/.nuke/` directory).

### Step 1: Clone or Download

1.  **Clone (Recommended)**: Clone the repository directly into your `~/.nuke/` folder:
    ```bash
    git clone git@github.com:CoffeeVeinStudio/CoffeeBoard.git
    ```
    The folder will be named `CoffeeBoard`.

2.  **Download (Alternative):** Download the ZIP file from GitHub and rename the extracted folder to **`CoffeeBoard`**. Place it inside your `~/.nuke/` directory.

### Step 2: Add to Nuke's Environment

Open your personal `menu.py` file (located in your `~/.nuke/` folder) and add the following Python code to dynamically include the plugin:

```python
import nuke
import os

# Get the path to the directory where this menu.py file is located (e.g., ~/.nuke/)
plugin_root = os.path.dirname(__file__)

# Add the CoffeeBoard folder to Nuke's plugin search paths
# Assumption: Your cloned folder is named "CoffeeBoard"
nuke.pluginAddPath(os.path.join(plugin_root, 'CoffeeBoard'))
```

## 🚀 Usage

Once the plugin is installed and Nuke is restarted, accessing and using the **Coffee Board** panel is simple:

1.  **Launch Nuke.**
2.  **Open the Panel Menu:** Right-click on any existing Nuke panel (such as your Viewer or Node Graph) to open the context menu.
3.  **Navigate to the Panel:** Go to **Windows > Custom > Coffee Board**.
4.  **Panel Placement:** The CoffeeBoard will open and function like any other Nuke panel. It can be docked to your current workspace or left as a floating window.
5.  **Core Functionality:**
    * **Drag & Drop:** Drag and drop any image file (JPG, PNG, TIFF, etc.) directly onto the panel to add it as a reference.
    * **Paste Images:** Paste images directly from your clipboard (e.g., after taking a screenshot).
    * **Right-Click Menu:** All functions, including saving and loading custom boards, are available when you right-click within the panel.
    