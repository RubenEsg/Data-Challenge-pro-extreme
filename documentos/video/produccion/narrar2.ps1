param(
    [Parameter(Mandatory = $true)][string]$Texto,    # UTF-8: una línea por subtítulo (lo que se dice)
    [Parameter(Mandatory = $true)][string]$Salida,   # WAV de salida (22,05 kHz, 16 bits, mono)
    [Parameter(Mandatory = $true)][string]$Marcas,   # TSV de salida: marca <tab> milisegundos de audio
    [int]$Tasa = 1                                    # SpeechSynthesizer.Rate (-10..10); la velocidad va por Rate, no por SSML
)
Add-Type -AssemblyName System.Speech
Add-Type -ReferencedAssemblies System.Speech -TypeDefinition @"
using System;
using System.Text;
using System.Globalization;
using System.Speech.Synthesis;
using System.Speech.AudioFormat;
public static class NarradorVideo {
    public static string Hablar(string ssml, string salida, int tasa) {
        var sb = new StringBuilder();
        using (var s = new SpeechSynthesizer()) {
            s.Rate = tasa;
            s.BookmarkReached += (o, e) => { lock (sb) { sb.AppendLine(e.Bookmark + "\t" + e.AudioPosition.TotalMilliseconds.ToString(CultureInfo.InvariantCulture)); } };
            s.SetOutputToWaveFile(salida, new SpeechAudioFormatInfo(22050, AudioBitsPerSample.Sixteen, AudioChannel.Mono));
            s.SpeakSsml(ssml);
            s.SetOutputToNull();
        }
        return sb.ToString();
    }
}
"@
$lineas = [System.IO.File]::ReadAllLines($Texto, [System.Text.Encoding]::UTF8) | Where-Object { $_.Trim() -ne "" }
$cuerpo = ""
$i = 0
foreach ($l in $lineas) {
    $cuerpo += "<mark name='c$i'/>" + [System.Security.SecurityElement]::Escape($l.Trim()) + " "
    $i++
}
$cuerpo += "<mark name='fin'/>"
$ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='es-MX'>" +
        "<voice name='Microsoft Sabina Desktop'>$cuerpo</voice></speak>"
$res = [NarradorVideo]::Hablar($ssml, $Salida, $Tasa)
[System.IO.File]::WriteAllText($Marcas, $res, (New-Object System.Text.UTF8Encoding($false)))
