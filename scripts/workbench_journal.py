# encoding: utf-8
# ANSYS Workbench journal (IronPython). Builds the Static Structural tensile analysis with the
# GUI visible, solves it for four materials plus a mesh-convergence study, and asks
# screenshot_watcher.ps1 to capture each stage. Launch it through run_simulation.ps1, which sets
# TENSILE_REPO to the repository root.
import os, time

REPO = os.environ["TENSILE_REPO"]
GEOM = os.path.join(REPO, "geometry", "tensile_specimen.igs")
SHOTS = os.path.join(REPO, "data", "screenshots_raw")
STEPS = os.path.join(REPO, "scripts", "mechanical_steps.py")
PROJECT = os.path.join(REPO, "ansys_project", "tensile.wbpj")
for d in (SHOTS, os.path.dirname(PROJECT)):
    if not os.path.isdir(d):
        os.makedirs(d)

def shot(name, target):
    done = os.path.join(SHOTS, name + ".done")
    f = open(os.path.join(SHOTS, name + ".req"), "w"); f.write(target); f.close()
    t = time.time()
    while not os.path.exists(done) and time.time() - t < 40:
        time.sleep(0.3)

def mech(call, name=None):
    cmd = "REPO = r'%s'\nexec(open(r'%s').read())\n%s\n" % (REPO, STEPS, call)
    model1.SendCommand(Language="Python", Command=cmd)
    if name:
        time.sleep(1.5)
        shot(name, "mech")

template1 = GetTemplate(TemplateName="Static Structural", Solver="ANSYS")
system1 = template1.CreateSystem()

engData = system1.GetContainer(ComponentName="Engineering Data")
EngData.OpenLibrary(Name="General Materials", Source="General_Materials.xml")
for m in ["Aluminum Alloy", "Polyethylene", "Concrete"]:
    engData.ImportMaterial(Name=m, Source="General_Materials.xml")

geometry1 = system1.GetContainer(ComponentName="Geometry")
geometry1.SetFile(FilePath=GEOM)
system1.GetComponent(Name="Geometry").Update(AllDependencies=True)
system1.GetComponent(Name="Model").Refresh()

model1 = system1.GetContainer(ComponentName="Model")
model1.Edit()
time.sleep(5)
mech("step_geometry()", "03_mechanical_geometry")
mech("step_materials()", "04_mechanical_materials")
mech("step_mesh()", "05_mechanical_mesh")
mech("step_fixed()", "06_mechanical_fixed_support")
mech("step_force()", "07_mechanical_force")
mech("step_results()", "08_mechanical_solution_objects")
names = ["Structural_Steel", "Aluminum_Alloy", "Polyethylene", "Concrete"]
for i in range(4):
    mech("step_solve_material(%d)" % i, "%02d_mechanical_solved_%s" % (9 + i, names[i]))
mech("step_convergence()")
mech("step_restore()", "14_mechanical_final_state")

Save(FilePath=PROJECT, Overwrite=True)
f = open(os.path.join(SHOTS, "ALL_DONE.flag"), "w"); f.write("done"); f.close()
