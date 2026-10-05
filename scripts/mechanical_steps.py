# Analysis steps executed inside ANSYS Mechanical.
# workbench_journal.py defines REPO (the repository root), exec()s this file and then
# calls one step_* function per SendCommand, so the GUI can redraw between steps.
import os, json

DATA = os.path.join(REPO, "data", "raw")
CONT = os.path.join(REPO, "data", "contours_raw")
PATHS = os.path.join(DATA, "paths")
for _d in (DATA, CONT, PATHS):
    if not os.path.isdir(_d):
        os.makedirs(_d)
MATERIALS = ["Structural Steel", "Aluminum Alloy", "Polyethylene", "Concrete"]

model = ExtAPI.DataModel.Project.Model
an = model.Analyses[0]
sol = an.Solution
body = model.Geometry.GetChildren(DataModelObjectCategory.Body, True)[0]

def L(s):
    f = open(os.path.join(DATA, "mech_log.txt"), "a"); f.write(str(s) + "\n"); f.close()

def fit():
    Graphics.Camera.SetSpecificViewOrientation(ViewOrientationType.Iso)
    Graphics.Camera.SetFit()

def show(obj):
    obj.Activate()
    Graphics.ViewOptions.ShowLegend = True
    fit()

def img_settings():
    s = Ansys.Mechanical.Graphics.GraphicsImageExportSettings()
    s.Resolution = GraphicsResolutionType.EnhancedResolution
    s.Background = GraphicsBackgroundType.White
    s.Width = 1600; s.Height = 900
    s.CurrentGraphicsDisplay = False
    return s

def export(obj, name):
    try:
        show(obj)
        Graphics.ExportImage(os.path.join(CONT, name + ".png"), GraphicsImageExportFormat.PNG, img_settings())
    except Exception as e:
        L("image fail %s: %s" % (name, e))

def end_faces():
    faces = list(ExtAPI.DataModel.GeoData.Assemblies[0].Parts[0].Bodies[0].Faces)
    xs = [f.Centroid[0] for f in faces]
    lo, hi = min(xs), max(xs)
    return [f for f in faces if abs(f.Centroid[0] - lo) < 1e-6], [f for f in faces if abs(f.Centroid[0] - hi) < 1e-6]

def sel(fs):
    s = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    s.Ids = [f.Id for f in fs]
    return s

def q(v):
    try:
        return v.Value
    except:
        return None

# ---------------- steps ----------------
def step_geometry():
    ExtAPI.Application.ActiveUnitSystem = MechanicalUnitSystem.StandardNMM
    open(os.path.join(DATA, "mech_log.txt"), "w").close()
    body.Material = "Structural Steel"
    show(model.Geometry)
    export(model.Geometry, "00_geometry")

def step_materials():
    model.Materials.Activate()

def step_mesh():
    model.Mesh.GenerateMesh()
    L("default mesh nodes=%s elements=%s" % (model.Mesh.Nodes, model.Mesh.Elements))
    show(model.Mesh)
    export(model.Mesh, "01_mesh")

def step_fixed():
    lo, hi = end_faces()
    fx = an.AddFixedSupport(); fx.Name = "Fixed Support"
    fx.Location = sel(hi)
    show(fx); export(fx, "02_fixed_support")

def step_force():
    lo, hi = end_faces()
    f = an.AddForce(); f.Name = "Force"
    f.Location = sel(lo)
    f.DefineBy = LoadDefineBy.Components
    f.XComponent.Output.DiscreteValues = [Quantity("-5000 [N]")]
    f.YComponent.Output.DiscreteValues = [Quantity("0 [N]")]
    f.ZComponent.Output.DiscreteValues = [Quantity("0 [N]")]
    show(f); export(f, "03_force")

def step_results():
    d = sol.AddTotalDeformation(); d.Name = "Total Deformation"
    e = sol.AddEquivalentElasticStrain(); e.Name = "Equivalent Elastic Strain"
    s = sol.AddEquivalentStress(); s.Name = "Equivalent Stress"
    dx = sol.AddDirectionalDeformation(); dx.Name = "Directional Deformation X"
    dx.NormalOrientation = NormalOrientationType.XAxis
    sx = sol.AddNormalStress(); sx.Name = "Normal Stress X"
    sx.NormalOrientation = NormalOrientationType.XAxis
    fr = sol.AddForceReaction(); fr.Name = "Reaction at Fixed Support"
    fr.BoundaryConditionSelection = ExtAPI.DataModel.GetObjectsByName("Fixed Support")[0]
    # centre-line path for distributions along the length
    cg = model.AddConstructionGeometry()
    p = cg.AddPath(); p.Name = "Centerline"
    p.StartXCoordinate = Quantity("-82.5 [mm]"); p.StartYCoordinate = Quantity("0 [mm]"); p.StartZCoordinate = Quantity("0 [mm]")
    p.EndXCoordinate = Quantity("82.5 [mm]"); p.EndYCoordinate = Quantity("0 [mm]"); p.EndZCoordinate = Quantity("0 [mm]")
    p.NumberOfSamplingPoints = 150
    for maker, nm in [(sol.AddEquivalentStress, "Path - Equivalent Stress"),
                      (sol.AddEquivalentElasticStrain, "Path - Equivalent Strain"),
                      (sol.AddTotalDeformation, "Path - Total Deformation")]:
        r = maker(); r.Name = nm
        r.ScopingMethod = GeometryDefineByType.Path
        r.Location = p
    sol.Activate()

def R(name):
    return ExtAPI.DataModel.GetObjectsByName(name)[0]

def step_solve_material(i):
    mat = MATERIALS[i]
    body.Material = mat
    an.Solve(True)
    tag = "%d_%s" % (i + 1, mat.replace(" ", "_"))
    d, e, s = R("Total Deformation"), R("Equivalent Elastic Strain"), R("Equivalent Stress")
    dx, sx, fr = R("Directional Deformation X"), R("Normal Stress X"), R("Reaction at Fixed Support")
    r = {"material": mat,
         "nodes": model.Mesh.Nodes, "elements": model.Mesh.Elements,
         "def_max": q(d.Maximum), "def_min": q(d.Minimum), "def_avg": q(d.Average),
         "strain_max": q(e.Maximum), "strain_min": q(e.Minimum), "strain_avg": q(e.Average),
         "stress_max": q(s.Maximum), "stress_min": q(s.Minimum), "stress_avg": q(s.Average),
         "dirx_max": q(dx.Maximum), "dirx_min": q(dx.Minimum),
         "sx_max": q(sx.Maximum), "sx_min": q(sx.Minimum), "sx_avg": q(sx.Average),
         "reaction_x": q(fr.XAxis), "reaction_total": q(fr.Total)}
    L(json.dumps(r))
    f = open(os.path.join(DATA, "result_%d.json" % (i + 1)), "w"); f.write(json.dumps(r, indent=2)); f.close()
    for nm, key in [("Path - Equivalent Stress", "stress"), ("Path - Equivalent Strain", "strain"), ("Path - Total Deformation", "deformation")]:
        try:
            R(nm).ExportToTextFile(os.path.join(PATHS, "%s_%s.txt" % (tag, key)))
        except Exception as ex:
            L("path export fail %s %s" % (nm, ex))
    export(d, tag + "_total_deformation")
    export(e, tag + "_equivalent_strain")
    export(s, tag + "_vonmises_stress")
    export(dx, tag + "_directional_deformation_x")
    show(s)

def step_convergence():
    body.Material = "Structural Steel"
    sz = model.Mesh.AddSizing(); sz.Name = "Convergence Sizing"
    s = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
    s.Ids = [ExtAPI.DataModel.GeoData.Assemblies[0].Parts[0].Bodies[0].Id]
    sz.Location = s
    rows = []
    for h in [6.0, 4.0, 3.0, 2.0, 1.5, 1.0]:
        sz.ElementSize = Quantity("%g [mm]" % h)
        model.Mesh.GenerateMesh()
        an.Solve(True)
        row = {"element_size_mm": h, "nodes": model.Mesh.Nodes, "elements": model.Mesh.Elements,
               "def_max": q(R("Total Deformation").Maximum), "stress_max": q(R("Equivalent Stress").Maximum),
               "strain_max": q(R("Equivalent Elastic Strain").Maximum)}
        L(json.dumps(row)); rows.append(row)
        f = open(os.path.join(DATA, "convergence.json"), "w"); f.write(json.dumps(rows, indent=2)); f.close()
    export(model.Mesh, "05_refined_mesh_1mm")
    export(R("Equivalent Stress"), "05_refined_1mm_Structural_Steel_vonmises_stress")
    export(R("Total Deformation"), "05_refined_1mm_Structural_Steel_total_deformation")
    show(R("Equivalent Stress"))

def step_restore():
    for o in ExtAPI.DataModel.GetObjectsByName("Convergence Sizing"):
        o.Delete()
    body.Material = "Structural Steel"
    model.Mesh.GenerateMesh()
    an.Solve(True)
    show(R("Equivalent Stress"))
    L("RESTORED")
