param([Parameter(Mandatory=$true)][string]$Path, [string]$Language='zh-Hans-CN')
$ErrorActionPreference='Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.FileAccessMode,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime] | Out-Null
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Await($Operation, $ResultType) {
    $task = $asTask.MakeGenericMethod($ResultType).Invoke($null,@($Operation))
    $task.Wait()
    return $task.Result
}
function AwaitAction($Operation) {
    $method=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and -not $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' } | Select-Object -First 1
    $task=$method.Invoke($null,@($Operation))
    $task.Wait()
}
$lang = New-Object Windows.Globalization.Language($Language)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }
if ($null -eq $engine) { throw '未安装可用的 Windows OCR 语言。' }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync((Resolve-Path -LiteralPath $Path).Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    if ([IO.Path]::GetExtension($Path) -ieq '.pdf') {
        [Windows.Data.Pdf.PdfDocument,Windows.Data.Pdf,ContentType=WindowsRuntime] | Out-Null
        [Windows.Data.Pdf.PdfPageRenderOptions,Windows.Data.Pdf,ContentType=WindowsRuntime] | Out-Null
        [Windows.Storage.Streams.InMemoryRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
        $document=Await ([Windows.Data.Pdf.PdfDocument]::LoadFromStreamAsync($stream)) ([Windows.Data.Pdf.PdfDocument])
        if($document.PageCount -gt 30){throw 'PDF 最多30页。'}
        $pages=New-Object System.Collections.Generic.List[object]
        $watch=[Diagnostics.Stopwatch]::StartNew()
        for($pageIndex=0;$pageIndex -lt [Math]::Min(10,$document.PageCount);$pageIndex++) {
            if($watch.Elapsed.TotalSeconds -gt 45){break}
            $pdfPage=$document.GetPage($pageIndex)
            $renderStream=New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
            $bitmap=$null
            try {
                $options=New-Object Windows.Data.Pdf.PdfPageRenderOptions
                $scale=[Math]::Min(2500,[Windows.Media.Ocr.OcrEngine]::MaxImageDimension)/[Math]::Max($pdfPage.Size.Width,$pdfPage.Size.Height)
                $options.DestinationWidth=[uint32][Math]::Max(1,[Math]::Floor($pdfPage.Size.Width*$scale))
                $options.DestinationHeight=[uint32][Math]::Max(1,[Math]::Floor($pdfPage.Size.Height*$scale))
                AwaitAction ($pdfPage.RenderToStreamAsync($renderStream,$options))
                $renderStream.Seek(0)
                $decoder=Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($renderStream)) ([Windows.Graphics.Imaging.BitmapDecoder])
                $bitmap=Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
                $result=Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
                $pages.Add(@{number=$pageIndex+1;text=(($result.Lines | ForEach-Object {$_.Text}) -join "`n")})
            } finally {if($null -ne $bitmap){$bitmap.Dispose()};$renderStream.Dispose();$pdfPage.Dispose()}
        }
        $payload=@{text=(($pages | ForEach-Object {$_.text}) -join "`n`n");pages=@($pages.ToArray());complete=($pages.Count -eq $document.PageCount);page_count=$document.PageCount;language=$engine.RecognizerLanguage.LanguageTag}
        [Console]::WriteLine(($payload | ConvertTo-Json -Compress -Depth 5))
        return
    }
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    try {
        if ($bitmap.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or $bitmap.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) { throw '图片尺寸过大，请缩小后导入。' }
        $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $payload = @{ text = (($result.Lines | ForEach-Object { $_.Text }) -join "`n"); language = $engine.RecognizerLanguage.LanguageTag }
        [Console]::WriteLine(($payload | ConvertTo-Json -Compress))
    } finally { if ($null -ne $bitmap) { $bitmap.Dispose() } }
} finally { if ($null -ne $stream) { $stream.Dispose() } }
