[CmdletBinding()]
param(
    [string]$OllamaUrl = 'http://127.0.0.1:11434'
)

$ErrorActionPreference = 'Stop'

$cases = @(
    @{
        Model = 'sim-qwen25-instruct:14b'
        System = 'Ты строгий рецензент. Верни только JSON.'
        User = 'Верни объект с полями passed=true и summary="готово".'
        Required = @('passed', 'summary')
        Schema = @{
            type = 'object'
            properties = @{
                passed = @{type = 'boolean'}
                summary = @{type = 'string'}
            }
            required = @('passed', 'summary')
        }
    },
    @{
        Model = 'sim-qwen25-coder:14b'
        System = 'Ты Python-разработчик. Верни только JSON.'
        User = 'Верни объект с summary и files; files содержит app/main.py с минимальным FastAPI GET /health.'
        Required = @('summary', 'files')
        Schema = @{
            type = 'object'
            properties = @{
                summary = @{type = 'string'}
                files = @{
                    type = 'array'
                    items = @{
                        type = 'object'
                        properties = @{
                            path = @{type = 'string'}
                            content = @{type = 'string'}
                        }
                        required = @('path', 'content')
                    }
                }
            }
            required = @('summary', 'files')
        }
    }
)

foreach ($case in $cases) {
    $body = @{
        model = $case.Model
        messages = @(
            @{role = 'system'; content = $case.System},
            @{role = 'user'; content = $case.User}
        )
        stream = $false
        keep_alive = '5m'
        format = $case.Schema
        options = @{
            num_predict = 256
            temperature = 0
        }
    } | ConvertTo-Json -Depth 10

    $watch = [Diagnostics.Stopwatch]::StartNew()
    $response = Invoke-RestMethod `
        -Uri ($OllamaUrl.TrimEnd('/') + '/api/chat') `
        -Method Post `
        -ContentType 'application/json; charset=utf-8' `
        -Body ([Text.Encoding]::UTF8.GetBytes($body)) `
        -TimeoutSec 180
    $watch.Stop()

    if ($response.done_reason -ne 'stop') {
        throw "$($case.Model) ended with $($response.done_reason)."
    }
    $parsed = $response.message.content | ConvertFrom-Json
    foreach ($field in $case.Required) {
        if ($null -eq $parsed.$field) { throw "$($case.Model) omitted $field." }
    }
    [pscustomobject]@{
        model = $case.Model
        seconds = [math]::Round($watch.Elapsed.TotalSeconds, 2)
        prompt_tokens = $response.prompt_eval_count
        output_tokens = $response.eval_count
        done_reason = $response.done_reason
    }
}
