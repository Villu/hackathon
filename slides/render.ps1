# Render every slide of the deck to PNG with PowerPoint (Windows, PowerPoint installed; no LibreOffice needed).
#   powershell -NoProfile -File slides\render.ps1                  # -> slides\render\Slide1.PNG ...
#   powershell -NoProfile -File slides\render.ps1 -Out C:\tmp\r    # other output folder
# Opens the deck read-only and without a window, so it also works while the deck is open in PowerPoint.
param(
    [string]$Deck = (Join-Path $PSScriptRoot "hackathon-slides.pptx"),
    [string]$Out = (Join-Path $PSScriptRoot "render")
)
if (Test-Path $Out) { Remove-Item -Recurse -Force $Out -Confirm:$false }
$app = New-Object -ComObject PowerPoint.Application
try {
    $p = $app.Presentations.Open((Resolve-Path $Deck).Path, $true, $false, $false)  # ReadOnly, Untitled, WithWindow
    $p.SaveAs($Out, 18)                                                            # 18 = ppSaveAsPNG, one file per slide
    Write-Output ("rendered {0} slides to {1}" -f $p.Slides.Count, $Out)
    $p.Close()
} finally {
    $app.Quit()
}
