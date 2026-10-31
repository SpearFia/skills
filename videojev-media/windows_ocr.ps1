# SPDX-License-Identifier: MIT OR Apache-2.0
# Local Windows OCR only. Return geometry and character counts, not recognized prose.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType=WindowsRuntime] | Out-Null
$awaitMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
function Await-Result($operation, [Type]$resultType) {
    $task = $awaitMethod.MakeGenericMethod($resultType).Invoke($null, @($operation))
    $task.Wait()
    return $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw 'No Windows OCR recognition language is installed' }
[Console]::WriteLine('{"status":"ready"}')
while ($null -ne ($requestLine = [Console]::ReadLine())) {
    try {
        $request = $requestLine | ConvertFrom-Json
        # A decoder can retain its input: detach from the file so the next frame can replace it.
        $memory = [System.IO.MemoryStream]::new([System.IO.File]::ReadAllBytes($request.path))
        $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($memory)
        $decoder = Await-Result ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-Result ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await-Result ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $words = @()
        $lineIndex = 0
        foreach ($line in $result.Lines) {
            foreach ($word in $line.Words) {
                $r = $word.BoundingRect
                $words += @{ x=$r.X; y=$r.Y; w=$r.Width; h=$r.Height; chars=$word.Text.Length; line=$lineIndex }
            }
            $lineIndex++
        }
        $response = @{ width=$bitmap.PixelWidth; height=$bitmap.PixelHeight; words=$words }
        $bitmap.Dispose()
        $stream.Dispose()
        $memory.Dispose()
        [Console]::WriteLine(($response | ConvertTo-Json -Depth 6 -Compress))
    } catch {
        [Console]::WriteLine((@{error=$_.Exception.Message} | ConvertTo-Json -Compress))
    }
}
