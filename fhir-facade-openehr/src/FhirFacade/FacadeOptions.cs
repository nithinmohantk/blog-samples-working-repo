using System.ComponentModel.DataAnnotations;

namespace FhirFacade;

public sealed class OpenEhrOptions
{
    /// <summary>Base of the openEHR REST API, ending in a slash, for example https://ehrbase.internal/ehrbase/rest/openehr/v1/.</summary>
    [Required]
    public Uri? BaseUrl { get; set; }

    /// <summary>Namespace of the patient identifier held in EHR_STATUS.subject.external_ref.</summary>
    [Required]
    public string SubjectNamespace { get; set; } = "";

    [Range(1, 60)]
    public int TimeoutSeconds { get; set; } = 10;
}

public sealed class AuthOptions
{
    /// <summary>OpenID Connect authority, for example https://login.microsoftonline.com/{tenant}/v2.0.</summary>
    public string? Authority { get; set; }

    [Required]
    public string Audience { get; set; } = "";

    /// <summary>Local development only. Program.cs refuses to start with this set outside Development.</summary>
    public string? DevelopmentIssuer { get; set; }

    public string? DevelopmentSigningSecret { get; set; }
}

public sealed class FhirOptions
{
    /// <summary>The address clients use, without a trailing slash, for example https://api.example.org/fhir.</summary>
    [Required]
    public Uri? PublicBaseUrl { get; set; }

    [Range(1, 100)]
    public int DefaultPageSize { get; set; } = 20;

    [Range(1, 500)]
    public int MaxPageSize { get; set; } = 100;
}
