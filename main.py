''' Create OUT nodes '''

import hou
from pprint import pprint as pp

# setting Node colors
out_color        = (0,0,0)               # Set Out Nodes color
out_merge_color  = (0.094, 0.369, 0.69)  # Set Object Merge Nodes color
out_rndr_color   = (0.8, 0.016, 0.16)    # set Render Geo Nodes color


def selNodes():
    ''' Outputs the selected node list '''
    sel = hou.selectedNodes()
    return sel

###############################################################
#################### Get and Create Node Name #################
###############################################################

def getNameUi():
    ''' This Fucntion will ouput the list [ok/cancel, user input name for node] '''
    sel = selNodes()
    if len(selNodes()) == 0:
        print ('----- IndexError: tuple index out of range ------')
        hou.ui.displayMessage('Please select a node for script to work', severity=hou.severityType.ImportantMessage)
        usr_input_list = ['error']
        return usr_input_list
    else:
        msg = 'Enter the out node name'
        usr_input_list = []
        sel_list = []
        [sel_list.append(each.name()) for each in sel]
        usr_input_list = hou.ui.readMultiInput(msg, buttons=('Ok', 'Cancel'),
                                               title='OUT_Nodes',
                                               input_labels=(sel_list),
                                               close_choice=1,
                                               severity=hou.severityType.ImportantMessage,
                                               help='Do not add OUT in prefix'
                                               )
        return usr_input_list


def createName():
    '''This fuction creates name for OUT node
        from either the user provided informationr or from the selected node
    '''
    out = 'OUT' #out node will always have this in start
    usr_name = getNameUi()
    name_list = []
    if usr_name[0] == 'error':
        #print 'nothing selected to create name'
        name_list = None
    else:
        if usr_name[0] == 0:
            for count, each in enumerate(usr_name[1]):
                if each=='':
                    each = '{0}_{1}'.format(out, selNodes()[count].name()).upper()
                else:
                    n = each.strip().replace(' ', '_')
                    each = '{0}_{1}'.format(out, n).upper()
                name_list.append(each)
        else:
            print 'canceled the operation'
    return name_list


###############################################################
###################### Create Null Node #######################
###############################################################


def createOutNull():
    '''Does pretty much what it says, creates null node/nodes
       with the name given by user or taken from selected nodes.
    '''
    sel = selNodes()
    name_list = createName()
    null_list = []
    if name_list == None:
        pass
    else:
        for count, n in enumerate(name_list):
            null = sel[count].createOutputNode('null', '{0}'.format(n))
            null.setColor(hou.Color(out_color))
            null.setGenericFlag(hou.nodeFlag.Render, True)
            null.setGenericFlag(hou.nodeFlag.Display, True)
            null_list.append(null)
            null.setCurrent(True, clear_all_selected=True)
    return null_list


###############################################################
################### Create Merge Out Nodes ####################
###############################################################


def createOutMerge():
    sel = selNodes()
    null_list = createOutNull()
    obj_merge = []
    if null_list == None:
        pass
    else:
        for null in null_list:
            name = null.name()[4:]

            #create object merge node
            om = null.parent().createNode('object_merge', 'IN_{0}'.format(name))
            om.parm('objpath1').set(null.path())
            om.parm('xformtype').set(1)
            om.setPosition(null.position())
            om.move((0, -2))
            om.setColor(hou.Color(out_merge_color))

            # adding comments to null node
            null.setComment('Dependency Link-\n{0}'.format(om.path()))
            null.setGenericFlag(hou.nodeFlag.DisplayComment, True)
            null.setColor(hou.Color(out_merge_color))

            obj_merge.append(om)
            # printing output
            print 'created nodes - <{0}> <{1}>'.format(null.path(), om.path())
    return obj_merge

###############################################################
################### Create Render Out Nodes ###################
###############################################################

def createRenderOut():
    sel = selNodes()
    null_list = createOutNull()
    if null_list == None:
        pass
    else:
        for null in null_list:
            name = null.name()[4:]
            parent_pos = null.parent().position()

            #create Render Geo Node
            rndr_geo_node = hou.node('/obj/').createNode('geo', 'RENDER_{0}'.format(name))
            rndr_geo_node.setPosition(parent_pos)
            rndr_geo_node.move((1.5, -1.5))
            rndr_geo_node.setComment('Dependency Link-\n{0}'.format(null.path()))
            rndr_geo_node.setGenericFlag(hou.nodeFlag.DisplayComment, True)
            rndr_geo_node.setColor(hou.Color(out_rndr_color))
            rndr_geo_node.moveToGoodPosition()

            #create Render obj merge node
            om = rndr_geo_node.createNode('object_merge', 'IN_{0}'.format(name))
            om.parm('objpath1').set(null.path())
            om.parm('xformtype').set(1)
            om.setColor(hou.Color(out_rndr_color))

            #create mantra node
            mantra = hou.node('out').createNode('mantra_mod', '{0}'.format(name)) #,
            mantra.parm('vobject').set('')
            mantra.parm('forceobject').set(rndr_geo_node.name())
            mantra.parm('vm_numaux').set('1')
            mantra.parm('vm_variable_plane1').set('all')
            mantra.parm('vm_lightexport1').set(1)
            mantra.moveToGoodPosition()

            #modify out node names
            mantra_name = mantra.name()
            null.setName('RENDER_{}'.format(mantra_name))
            om.setName('IN_{}'.format(mantra_name))

            #modify out null settings
            null.setComment('Dependency Link-\n{0}'.format(om.path()))
            null.setGenericFlag(hou.nodeFlag.DisplayComment, True)
            null.setColor(hou.Color(out_rndr_color))