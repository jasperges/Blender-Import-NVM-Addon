import bpy
import os
from mathutils import Matrix, Vector
import math
from math import radians
import time
from nvm_import_export.stop_watch import StopWatch
import numpy as np
from nvm_import_export.point import Point

def get_world_matrix_from_translation_vec(translation_vec, rotation):
    t = Vector(translation_vec).to_4d()
    camera_rotation = Matrix()
    for row in range(3):
        camera_rotation[row][0:3] = rotation[row]

    camera_rotation.transpose()  # = Inverse rotation

    camera_center = -(camera_rotation * t)  # Camera position in world coordinates
    camera_center[3] = 1.0

    camera_rotation = camera_rotation.copy()
    camera_rotation.col[3] = camera_center  # Set translation to camera position
    return camera_rotation

def invert_y_and_z_axis(input_matrix_or_vector):
    """
    VisualSFM and Blender use coordinate systems, which differ in the y and z coordinate
    This Function inverts the y and the z coordinates in the corresponding matrix / vector entries
    Iinvert y and z axis <==> rotation by 180 degree around the x axis
    """
    output_matrix_or_vector = input_matrix_or_vector.copy()
    output_matrix_or_vector[1] = -output_matrix_or_vector[1]
    output_matrix_or_vector[2] = -output_matrix_or_vector[2]
    return output_matrix_or_vector

def add_obj(data, obj_name, deselect_others=False):
    scene = bpy.context.scene

    if deselect_others:
        for obj in scene.objects:
            obj.select = False

    new_obj = bpy.data.objects.new(obj_name, data)
    scene.objects.link(new_obj)
    new_obj.select = True

    if scene.objects.active is None or scene.objects.active.mode == 'OBJECT':
        scene.objects.active = new_obj
    return new_obj

def set_object_parent(child_object_name, parent_object_name, keep_transform=False):
    child_object_name.parent = parent_object_name
    if keep_transform:
        child_object_name.matrix_parent_inverse = parent_object_name.matrix_world.inverted()

def add_empty(empty_name):
    empty_obj = bpy.data.objects.new(empty_name, None)
    bpy.context.scene.objects.link(empty_obj)
    return empty_obj

def add_points_as_mesh(op, points, add_points_as_particle_system, mesh_type, point_extent):
    op.report({'INFO'}, 'Adding Points: ...')
    stop_watch = StopWatch()
    name = "Point_Cloud"
    mesh = bpy.data.meshes.new(name)
    mesh.update()
    mesh.validate()

    point_world_coordinates = [tuple(point.coord) for point in points]

    mesh.from_pydata(point_world_coordinates, [], [])
    meshobj = add_obj(mesh, name)

    if add_points_as_particle_system or add_meshes_at_vertex_positions:
        op.report({'INFO'}, 'Representing Points in the Point Cloud with Meshes: True')
        op.report({'INFO'}, 'Mesh Type: ' + str(mesh_type))

        # The default size of elements added with 
        #   primitive_cube_add, primitive_uv_sphere_add, etc. is (2,2,2)
        point_scale = point_extent * 0.5 

        bpy.ops.object.select_all(action='DESELECT')
        if mesh_type == "PLANE":
            bpy.ops.mesh.primitive_plane_add(radius=point_scale)
        elif mesh_type == "CUBE":
            bpy.ops.mesh.primitive_cube_add(radius=point_scale)
        elif mesh_type == "SPHERE":
            bpy.ops.mesh.primitive_uv_sphere_add(radius=point_scale)
        else:
            bpy.ops.mesh.primitive_uv_sphere_add(radius=point_scale)
        viz_mesh = bpy.context.object

        if add_points_as_particle_system:
            
            material_name = "PointCloudMaterial"
            material = bpy.data.materials.new(name=material_name)
            viz_mesh.data.materials.append(material)
            
            # enable cycles, otherwise the material has no nodes
            bpy.context.scene.render.engine = 'CYCLES'
            material.use_nodes = True
            node_tree = material.node_tree
            if 'Material Output' in node_tree.nodes:    # is created by default
                material_output_node = node_tree.nodes['Material Output']
            else:
                material_output_node = node_tree.nodes.new('ShaderNodeOutputMaterial')
            if 'Diffuse BSDF' in node_tree.nodes:       # is created by default
                diffuse_node = node_tree.nodes['Diffuse BSDF']
            else:
                diffuse_node = node_tree.nodes.new("ShaderNodeBsdfDiffuse")
            node_tree.links.new(diffuse_node.outputs['BSDF'], material_output_node.inputs['Surface'])
            
            if 'Image Texture' in node_tree.nodes:
                image_texture_node = node_tree.nodes['Image Texture']
            else:
                image_texture_node = node_tree.nodes.new("ShaderNodeTexImage")
            node_tree.links.new(image_texture_node.outputs['Color'], diffuse_node.inputs['Color'])
            
            vis_image_height = 1
            
            # To view the texture we set the height of the texture to vis_image_height 
            image = bpy.data.images.new('ParticleColor', len(point_world_coordinates), vis_image_height)
            
            # working on a copy of the pixels results in a MASSIVE performance speed
            local_pixels = list(image.pixels[:])
            
            num_points = len(points)
            
            for j in range(vis_image_height):
                for point_index, point in enumerate(points):
                    column_offset = point_index * 4     # (R,G,B,A)
                    row_offset = j * 4 * num_points
                    color = point.color 
                    # Order is R,G,B, opacity
                    local_pixels[row_offset + column_offset] = color[0] / 255.0
                    local_pixels[row_offset + column_offset + 1] = color[1] / 255.0
                    local_pixels[row_offset + column_offset + 2] = color[2] / 255.0
                    # opacity (0 = transparent, 1 = opaque)
                    #local_pixels[row_offset + column_offset + 3] = 1.0    # already set by default   
                
            image.pixels = local_pixels[:]  
            
            image_texture_node.image = image
            particle_info_node = node_tree.nodes.new('ShaderNodeParticleInfo')
            divide_node = node_tree.nodes.new('ShaderNodeMath')
            divide_node.operation = 'DIVIDE'
            node_tree.links.new(particle_info_node.outputs['Index'], divide_node.inputs[0])
            divide_node.inputs[1].default_value = num_points
            shader_node_combine = node_tree.nodes.new('ShaderNodeCombineXYZ')
            node_tree.links.new(divide_node.outputs['Value'], shader_node_combine.inputs['X'])
            node_tree.links.new(shader_node_combine.outputs['Vector'], image_texture_node.inputs['Vector'])
            
            if len(meshobj.particle_systems) == 0:
                meshobj.modifiers.new("particle sys", type='PARTICLE_SYSTEM')
                particle_sys = meshobj.particle_systems[0]
                settings = particle_sys.settings
                settings.type = 'HAIR'
                settings.use_advanced_hair = True
                settings.emit_from = 'VERT'
                settings.count = len(point_world_coordinates)
                # The final object extent is hair_length * obj.scale 
                settings.hair_length = 100           # This must not be 0
                settings.use_emit_random = False
                settings.render_type = 'OBJECT'
                settings.dupli_object = viz_mesh
            
        bpy.context.scene.update
    else:
        op.report({'INFO'}, 'Representing Points in the Point Cloud with Meshes: False')
    op.report({'INFO'}, 'Duration: ' + str(stop_watch.get_elapsed_time()))
    op.report({'INFO'}, 'Adding Points: Done')

    
def add_cameras(op, 
                cameras, 
                path_to_images=None,
                add_image_planes=False,
                convert_camera_coordinate_system=True,
                cameras_parent='Cameras',
                camera_group_name='Camera Group',
                image_planes_parent='Image Planes',
                image_plane_group_name='Image Plane Group',
                camera_scale=1.0):

    """
    ======== The images are currently only shown in BLENDER RENDER ========
    ======== Make sure to enable TEXTURE SHADING in the 3D view to make the images visible ========

    :param cameras:
    :param path_to_images:
    :param add_image_planes:
    :param convert_camera_coordinate_system:
    :param cameras_parent:
    :param camera_group_name:
    :param image_plane_group_name:
    :return:
    """
    op.report({'INFO'}, 'Adding Cameras: ...')
    stop_watch = StopWatch()
    cameras_parent = add_empty(cameras_parent)
    cameras_parent.hide = True
    cameras_parent.hide_render = True
    camera_group = bpy.data.groups.new(camera_group_name)

    if add_image_planes:
        op.report({'INFO'}, 'Adding image planes: True')
        image_planes_parent = add_empty(image_planes_parent)
        image_planes_group = bpy.data.groups.new(image_plane_group_name)
    else:
        op.report({'INFO'}, 'Adding image planes: False')

    # Adding cameras and image planes:
    for index, camera in enumerate(cameras):

        start_time = stop_watch.get_elapsed_time()
        assert camera.width is not None and camera.height is not None

        # camera_name = "Camera %d" % index     # original code
        # Replace the camera name so it matches the image name (without extension)
        image_file_name_stem = os.path.splitext(os.path.basename(camera.file_name))[0]
        camera_name = image_file_name_stem + '_cam'

        focal_length = camera.get_focal_length()
        op.report({'INFO'}, 'focal_length: ' + str(focal_length))
        #op.report({'INFO'}, 'camera.get_calibration_mat(): ' + str(camera.get_calibration_mat()))
        op.report({'INFO'}, 'width: ' + str(camera.width))
        op.report({'INFO'}, 'height: ' + str(camera.height))

        # Add camera:
        bcamera = bpy.data.cameras.new(camera_name)
        #  Adjust field of view
        bcamera.angle = math.atan(max(camera.width, camera.height) / (focal_length * 2.0)) * 2.0

        # Adjust principal point
        p_x, p_y = camera.get_principal_point()
        
        op.report({'INFO'}, 'p_x: ' + str(p_x))
        op.report({'INFO'}, 'p_y: ' + str(p_y))


        # https://blender.stackexchange.com/questions/58235/what-are-the-units-for-camera-shift
        # This is measured however in relation to the largest dimension of the rendered frame size. 
        # So lets say you are rendering in Full HD, that is 1920 x 1080 pixel image; 
        # a frame shift if 1 unit will shift exactly 1920 pixels in any direction, that is up/down/left/right.
        max_extent = max(camera.width, camera.height)
        bcamera.shift_x = (camera.width / 2.0 - p_x) / float(max_extent)
        bcamera.shift_y = (camera.height / 2.0 - p_y) / float(max_extent)

        camera_object = add_obj(bcamera, camera_name)

        translation_vec = camera.get_translation_vec()
        rotation_mat = camera.get_rotation_mat()
        # Transform the camera coordinate system from computer vision camera coordinate frames to the computer
        # vision camera coordinate frames
        # That is, rotate the camera matrix around the x axis by 180 degree, i.e. invert the x and y axis
        rotation_mat = invert_y_and_z_axis(rotation_mat)
        translation_vec = invert_y_and_z_axis(translation_vec)
        camera_object.matrix_world = get_world_matrix_from_translation_vec(translation_vec, rotation_mat)

        camera_object.scale *= camera_scale

        set_object_parent(camera_object, cameras_parent, keep_transform=True)
        camera_group.objects.link(camera_object)

        if add_image_planes:
            path_to_image = os.path.join(path_to_images, os.path.basename(camera.file_name))
            
            if os.path.isfile(path_to_image):
                
                op.report({'INFO'}, 'Adding image plane for: ' + str(path_to_image))

                # Group image plane and camera:
                camera_image_plane_pair = bpy.data.groups.new(
                    "Camera Image Plane Pair Group %s" % image_file_name_stem)
                camera_image_plane_pair.objects.link(camera_object)

                image_plane_name = image_file_name_stem + '_image_plane'
                
                px, py = camera.get_principal_point()

                # do not add image planes by default, this is slow !
                bimage = bpy.data.images.load(path_to_image)
                image_plane_obj = add_camera_image_plane(
                    rotation_mat, 
                    translation_vec, 
                    bimage, 
                    camera.width, 
                    camera.height, 
                    focal_length, 
                    px=px,
                    py=py,
                    name=image_plane_name, 
                    op=op)
                camera_image_plane_pair.objects.link(image_plane_obj)

                set_object_parent(image_plane_obj, image_planes_parent, keep_transform=True)
                image_planes_group.objects.link(image_plane_obj)

        end_time = stop_watch.get_elapsed_time()

    op.report({'INFO'}, 'Duration: ' + str(stop_watch.get_elapsed_time()))
    op.report({'INFO'}, 'Adding Cameras: Done')

def add_camera_image_plane(rotation_mat, translation_vec, bimage, width, height, focal_length, px, py, name, op):
    """
    Create mesh for image plane
    """
    op.report({'INFO'}, 'add_camera_image_plane: ...')
    op.report({'INFO'}, 'name: ' + str(name))
    bpy.context.scene.render.engine = 'CYCLES'
    mesh = bpy.data.meshes.new(name)
    mesh.update()
    mesh.validate()

    plane_distance = 1.0  # Distance from camera position
    # Right vector in view frustum at plane_distance:
    right = Vector((1, 0, 0)) * (width / focal_length) * plane_distance
    # Up vector in view frustum at plane_distance:
    up = Vector((0, 1, 0)) * (height / focal_length) * plane_distance
    # Camera view direction:
    view_dir = -Vector((0, 0, 1)) * plane_distance
    plane_center = view_dir
    
    relative_shift_x = float((width / 2.0 - px) / float(width))
    relative_shift_y = float((height / 2.0 - py) / float(height))
    
    op.report({'INFO'}, 'relative_shift_x: ' + str(relative_shift_x))
    op.report({'INFO'}, 'relative_shift_y:' + str(relative_shift_y))

    corners = ((-0.5, -0.5),
               (+0.5, -0.5),
               (+0.5, +0.5),
               (-0.5, +0.5))
    points = [(plane_center + (c[0] + relative_shift_x) * right + (c[1] + relative_shift_y) * up)[0:3] for c in corners]
    mesh.from_pydata(points, [], [[0, 1, 2, 3]])
    
    # Assign image to face of image plane:
    uvmap = mesh.uv_textures.new()
    face = uvmap.data[0]
    face.image = bimage

    # Add mesh to new image plane object:
    mesh_obj = add_obj(mesh, name)

    image_plane_material = bpy.data.materials.new(
        name="image_plane_material")
    # Adds "Diffuse BSDF" and a "Material Output" node
    image_plane_material.use_nodes = True
    image_plane_material.use_shadeless = True
    
    # get the "Diffuse BSDF" node
    nodes = image_plane_material.node_tree.nodes
    links = image_plane_material.node_tree.links
    
    shader_node_tex_image = nodes.new(type='ShaderNodeTexImage')
    shader_node_diffuse_bsdf = nodes.get('Diffuse BSDF')
    
    links.new(
        shader_node_tex_image.outputs['Color'], 
        shader_node_diffuse_bsdf.inputs['Color'])
        
    shader_node_tex_image.image = bimage
    
    # Assign it to object
    if mesh_obj.data.materials:
        # assign to 1st material slot
        mesh_obj.data.materials[0] = image_plane_material
    else:
        # no slots
        mesh_obj.data.materials.append(image_plane_material)
    
    world_matrix = get_world_matrix_from_translation_vec(translation_vec, rotation_mat)
    mesh_obj.matrix_world = world_matrix
    mesh.update()
    mesh.validate()
    op.report({'INFO'}, 'add_camera_image_plane: Done')
    return mesh_obj

def set_principal_point_for_cameras(cameras, default_pp_x, default_pp_y, op):
    
    if not math.isnan(default_pp_x) and not math.isnan(default_pp_y):
        op.report({'WARNING'}, 'Setting principal points to default values!')
    else:
        op.report({'WARNING'}, 'Setting principal points to image centers!')
        default_pp_x = cameras[0].width / 2.0
        default_pp_y = cameras[0].height / 2.0
    
    for camera in cameras:
        if not camera.is_principal_point_initialized():
            camera.set_principal_point([default_pp_x, default_pp_y])

def principal_points_initialized(cameras):
    principal_points_initialized = True
    for camera in cameras:
        if not camera.is_principal_point_initialized():
            principal_points_initialized = False
            break
    return principal_points_initialized

def adjust_render_settings_if_possible(op, cameras):
    
    possible = True
    width = cameras[0].width
    height = cameras[0].height
    for cam in cameras:
        if cam.width != width or cam.height != height:
            possible = False
            break
    if possible:
        bpy.context.scene.render.resolution_x = width
        bpy.context.scene.render.resolution_y = height
    


from bpy.props import (CollectionProperty,
                       StringProperty,
                       BoolProperty,
                       EnumProperty,
                       FloatProperty,
                       IntProperty,
                       )

from bpy_extras.io_utils import (ImportHelper,
                                 ExportHelper,
                                 axis_conversion)

class ImportNVM(bpy.types.Operator, ImportHelper):
    
    # http://sinestesia.co/blog/tutorials/using-blenders-filebrowser-with-python/
    # https://www.blender.org/forum/viewtopic.php?t=26470
    
    """Load a NVM file"""
    bl_idname = "import_scene.nvm"
    bl_label = "Import NVM"
    bl_options = {'UNDO'}

    files = CollectionProperty(
        name="File Path",
        description="File path used for importing the NVM file",
        type=bpy.types.OperatorFileListElement)

    directory = StringProperty()

    import_cameras = BoolProperty(
        name="Import Cameras",
        description = "Import Cameras", 
        default=True)
    default_width = IntProperty(
        name="Default Width",
        description = "Width, which will be used used if corresponding image is not found.", 
        default=-1)
    default_height = IntProperty(
        name="Default Height", 
        description = "Height, which will be used used if corresponding image is not found.",
        default=-1)
    default_pp_x = FloatProperty(
        name="Principal Point X Component",
        description = "Principal Point X Component, which will be used if not contained in the NVM file. " + \
                      "If no value is provided, the principal point is set to the image center.", 
        default=float('nan'))
    default_pp_y = FloatProperty(
        name="Principal Point Y Component", 
        description = "Principal Point Y Component, which will be used if not contained in the NVM file. " + \
                      "If no value is provided, the principal point is set to the image center.", 
        default=float('nan'))
    add_image_planes = BoolProperty(
        name="Add an Image Plane for each Camera",
        description = "Add an Image Plane for each Camera", 
        default=True)
    path_to_images = StringProperty(
        name="Image Directory",
        description = "Path to the directory of images. If no path is provided, the paths in the nvm file are used.", 
        default="",
        # Can not use subtype='DIR_PATH' while importing another file (i.e. .nvm)
        )
    adjust_render_settings = BoolProperty(
        name="Adjust Render Settings",
        description = "Adjust the render settings according to the corresponding images. "  +
                      "All images have to be captured with the same device). " +
                      "If disabled the visualization of the camera cone in 3D view might be incorrect.", 
        default=True)
    camera_extent = FloatProperty(
        name="Initial Camera Extent (in Blender Units)", 
        description = "Initial Camera Extent (Visualization)",
        default=1)

    import_points = BoolProperty(
        name="Import Points",
        description = "Import Points", 
        default=True)
    add_points_as_particle_system = BoolProperty(
        name="Add Points as Particle System",
        description="Use a particle system to represent vertex positions with objects",
        default=True)
    mesh_items = [
        ("CUBE", "Cube", "", 1),
        ("SPHERE", "Sphere", "", 2),
        ("PLANE", "Plane", "", 3)
        ]
    mesh_type = EnumProperty(
        name="Mesh Type",
        description = "Select the vertex representation mesh type.", 
        items=mesh_items)
    point_extent = FloatProperty(
        name="Initial Point Extent (in Blender Units)", 
        description = "Initial Point Extent for meshes at vertex positions",
        default=0.01)


    filename_ext = ".nvm"
    filter_glob = StringProperty(default="*.nvm", options={'HIDDEN'})

    def execute(self, context):
        paths = [os.path.join(self.directory, name.name)
                 for name in self.files]
        if not paths:
            paths.append(self.filepath)
            
        self.report({'INFO'}, 'paths: ' + str(paths))

        from nvm_import_export.nvm_file_handler import NVMFileHandler

        for path in paths:
            
            # by default search for the images in the nvm directory
            if self.path_to_images == '':
                self.path_to_images = os.path.dirname(path)
            
            cameras, points = NVMFileHandler.parse_nvm_file(path, self)
            
            # https://blender.stackexchange.com/questions/717/is-it-possible-to-print-to-the-report-window-in-the-info-view
            #   The color depends on the type enum: INFO gets green, WARNING light red, and ERROR dark red
            # https://docs.blender.org/api/blender_python_api_2_78_release/bpy.types.Operator.html?highlight=report#bpy.types.Operator.report
            self.report({'INFO'}, 'Number cameras: ' + str(len(cameras)))
            self.report({'INFO'}, 'Number points: ' + str(len(points)))
            
            if self.import_cameras:
                cameras, success = NVMFileHandler.parse_camera_image_files(
                    cameras, self.path_to_images, self.default_width, self.default_height, self)
                
                if success:
                    # principal point information may be provided in the NVM file
                    if not principal_points_initialized(cameras):
                        set_principal_point_for_cameras(
                            cameras, 
                            self.default_pp_x,
                            self.default_pp_y,
                            self)
                    
                    if self.adjust_render_settings:
                        adjust_render_settings_if_possible(
                            self, 
                            cameras)
                    add_cameras(
                        self, 
                        cameras, 
                        path_to_images=self.path_to_images, 
                        add_image_planes=self.add_image_planes, 
                        camera_scale=self.camera_extent)
                else:
                    return {'FINISHED'}
                
            if self.import_points:
                add_points_as_mesh(
                    self, 
                    points, 
                    self.add_points_as_particle_system, 
                    self.mesh_type, 
                    self.point_extent)

        return {'FINISHED'}
