$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw 'Команда ollama не найдена в PATH.'
}

$required = @(
    'qwen2.5:14b-instruct',
    'qwen2.5-coder:14b'
)
$installed = @(ollama list | Select-Object -Skip 1 | ForEach-Object {
    ($_ -split '\s+')[0]
})

foreach ($model in $required) {
    if ($installed -notcontains $model) {
        throw "Не установлена базовая модель $model. Сначала выполните: ollama pull $model"
    }
}

ollama create sim-qwen25-instruct:14b -f (Join-Path $Root 'Modelfile.instruct')
if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать sim-qwen25-instruct:14b.' }

ollama create sim-qwen25-coder:14b -f (Join-Path $Root 'Modelfile.coder')
if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать sim-qwen25-coder:14b.' }

$models = ollama list | Out-String
if ($models -notmatch [regex]::Escape('sim-qwen25-instruct:14b')) {
    throw 'Alias sim-qwen25-instruct:14b отсутствует после установки.'
}
if ($models -notmatch [regex]::Escape('sim-qwen25-coder:14b')) {
    throw 'Alias sim-qwen25-coder:14b отсутствует после установки.'
}

Write-Host 'Модели SIM созданы успешно:'
Write-Host '  sim-qwen25-instruct:14b (context 30720)'
Write-Host '  sim-qwen25-coder:14b    (context 30720)'
