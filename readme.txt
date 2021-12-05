steps-

01. create your scripts in main, or whichever file you prefer


02. create indiviual python files in same loaction of main script, write in the following code-
 - null_out.py
	- __import__("main").createOutNull()
 - merge_out.py
 	- __import__("main").createOutMerge()
 - render_out.py
 	- __import__("main").createRenderOut()
 
 
 
03. create an xml file in your $HOME directory, and fill in following data -
 - OPmenu.xml
 
<?xml version="1.0" encoding="UTF-8"?>
<menuDocument>
  <menu>
    <scriptItem id="null_out">
      <label>Null Out</label>
      <scriptPath>C:/Users/deepa/Documents/_houdini_/scripts/out_tools/null_out.py</scriptPath>
<menuDocument>
  <menu>
    <scriptItem id="merge_out">
      <label>Merge Out</label>
      <scriptPath>C:/Users/deepa/Documents/_houdini_/scripts/out_tools/merge_out.py</scriptPath>
<menuDocument>
  <menu>
    <scriptItem id="render_out">
      <label>Render Out</label>
      <scriptPath>C:/Users/deepa/Documents/_houdini_/scripts/out_tools/render_out.py</scriptPath>
    </scriptItem>
  </menu>
</menuDocument>

This works, but is not the correct code


04. go to your 123.py file, in $HOME, and append it to the sys.path list

import sys
import_list= [
    'C:/Users/deepa/Documents/houdini18.5/scripts',
    'C:/Users/deepa/Documents/_houdini_/scripts/out_tools'
]
for p in import_list:
    sys.path.append(p) 