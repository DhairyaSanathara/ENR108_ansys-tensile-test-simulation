# Watches for <name>.req files written by workbench_journal.py and captures the requested
# ANSYS window (mech = Mechanical, wb = Workbench) to <name>.png, then writes <name>.done.
param([Parameter(Mandatory = $true)][string]$ShotsDir, [int]$TimeoutMinutes = 40)

Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class ShotUser32 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, int f, int e);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
[ShotUser32]::SetProcessDPIAware() | Out-Null
New-Item -ItemType Directory -Force $ShotsDir | Out-Null
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)

while (-not (Test-Path "$ShotsDir\ALL_DONE.flag") -and (Get-Date) -lt $deadline) {
  foreach ($req in Get-ChildItem $ShotsDir -Filter *.req) {
    $target = (Get-Content $req.FullName -Raw).Trim()
    $procName = if ($target -eq 'mech') { 'AnsysWBU' } else { 'AnsysFWW' }
    $p = Get-Process -Name $procName -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($p) {
      # Alt key press lets this process take the foreground; then maximise and capture the window only
      [ShotUser32]::keybd_event(0x12, 0, 0, 0); [ShotUser32]::keybd_event(0x12, 0, 2, 0)
      [ShotUser32]::ShowWindow($p.MainWindowHandle, 3) | Out-Null
      [ShotUser32]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
      Start-Sleep -Milliseconds 2500
      $r = New-Object ShotUser32+RECT
      [ShotUser32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
      $sb = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
      $x = [Math]::Max($r.Left, 0); $y = [Math]::Max($r.Top, 0)
      $w = [Math]::Min($r.Right, $sb.Width) - $x; $h = [Math]::Min($r.Bottom, $sb.Height) - $y
      $bmp = New-Object System.Drawing.Bitmap $w, $h
      $g = [System.Drawing.Graphics]::FromImage($bmp)
      $g.CopyFromScreen($x, $y, 0, 0, $bmp.Size)
      $bmp.Save(($req.FullName -replace '\.req$', '.png'), [System.Drawing.Imaging.ImageFormat]::Png)
      $g.Dispose(); $bmp.Dispose()
    }
    Set-Content ($req.FullName -replace '\.req$', '.done') 'ok'
    Remove-Item $req.FullName
  }
  Start-Sleep -Milliseconds 300
}
Get-ChildItem $ShotsDir -Filter *.done | Remove-Item
