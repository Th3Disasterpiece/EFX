## Enter The VFX (EFX) Tools for Houdini

This repository contains a collection of Python tools, shelf toolbars, and utility scripts for FX artists working with Houdini. These tools aim to streamline tasks and enhance the user experience within the Houdini environment.

---

### Tools & Scripts:

- **Out Tools**:
  - Basic Python scripts accessible via right-clicking on nodes.
  - Include Null out nodes, Object merge and Out nodes, and Render Out nodes.

**Video Demo**

[<img src="https://github.com/Th3Disasterpiece/EFX/blob/master/config/thumbnails/out_tools_snapshot.png" width="200">](https://vimeo.com/653346110)

---

- **Snip UI**:
  - A work-in-progress UI for saving and importing a collection of nodes to disk for quick access.
  - Helps create a personalized library of commonly used systems, examples, vex and python snippets, and setups.

**SnipUI Shelftool**

<img src="https://github.com/Th3Disasterpiece/EFX/blob/master/config/thumbnails/snipUIShelftool_snapshot.png" alt="SnipUI Shelftool" width="600">

**WriteSnipUI (Completed)**

<img src="https://github.com/Th3Disasterpiece/EFX/blob/master/config/thumbnails/writeSnipUI_snapshot.png" alt="Write SnipUI" width="300">

**ReadSnipUI (Incomplete)**

<img src="https://github.com/Th3Disasterpiece/EFX/blob/master/config/thumbnails/readSnipUI_snapshot.png" alt="Read SnipUI" width="500">

---

### Installation:

To get started with these EFX tools, follow these steps:
1. Clone or download this repository to your local machine.
2. Ensure you have the necessary dependencies installed, such as PySide2, and are using Houdini 20 (python3.10).
3. Copy the "EFX.json" file from the downloaded repository to the "packages" directory in your Houdini installation folder.
4. Open the "EFX.json" file and replace the value of the "EFX" key with the path to the downloaded repository on your machine.

---

### Contributing:

Contributions to this project are welcome! If you have ideas for additional features, improvements, or bug fixes, feel free to submit a pull request. Please ensure that any contributions align with the goals and scope of this project.
