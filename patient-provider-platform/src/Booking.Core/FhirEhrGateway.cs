using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Booking.Core;

/// <summary>
/// Records an appointment on a FHIR R4 server with a conditional create. The platform's appointment id is
/// sent as a business identifier and as the If-None-Exist condition, so a second delivery of the same event
/// matches the first and creates nothing. This is the generic R4 interaction; an EHR that exposes booking as
/// an operation instead of a create needs its own implementation of <see cref="IEhrGateway"/>.
/// </summary>
public sealed class FhirEhrGateway(HttpClient http, string identifierSystem) : IEhrGateway
{
    private static readonly MediaTypeHeaderValue FhirJson = new("application/fhir+json");

    public async Task<EhrOutcome> RecordAppointmentAsync(AppointmentEvent appointment, CancellationToken cancellationToken)
    {
        using HttpRequestMessage request = new(HttpMethod.Post, "Appointment");
        request.Headers.Accept.ParseAdd("application/fhir+json");
        request.Headers.TryAddWithoutValidation("If-None-Exist", $"identifier={Uri.EscapeDataString(identifierSystem)}|{Uri.EscapeDataString(appointment.AppointmentId)}");
        request.Content = new StringContent(ToFhir(appointment, identifierSystem).ToJsonString(), Encoding.UTF8);
        request.Content.Headers.ContentType = FhirJson;

        using HttpResponseMessage response = await http.SendAsync(request, cancellationToken).ConfigureAwait(false);
        if (response.StatusCode is not (HttpStatusCode.Created or HttpStatusCode.OK))
        {
            // The body may contain an OperationOutcome that echoes request content, so it is not put in the message.
            throw new HttpRequestException($"EHR refused the appointment with status {(int)response.StatusCode}.", null, response.StatusCode);
        }

        string id = response.Headers.Location?.ToString().Split("/Appointment/").Last().Split('/')[0] ?? await ReadIdAsync(response, cancellationToken).ConfigureAwait(false);
        return new EhrOutcome(response.StatusCode == HttpStatusCode.Created, id);
    }

    public static JsonObject ToFhir(AppointmentEvent appointment, string identifierSystem) => new()
    {
        ["resourceType"] = "Appointment",
        ["identifier"] = new JsonArray(new JsonObject { ["system"] = identifierSystem, ["value"] = appointment.AppointmentId }),
        ["status"] = "booked",
        ["slot"] = new JsonArray(new JsonObject { ["reference"] = $"Slot/{appointment.SlotId}" }),
        ["created"] = appointment.RecordedAt.ToString("yyyy-MM-ddTHH:mm:sszzz"),
        ["participant"] = new JsonArray(new JsonObject
        {
            ["actor"] = new JsonObject { ["reference"] = appointment.PatientReference },
            ["status"] = "accepted",
        }),
    };

    private static async Task<string> ReadIdAsync(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.Content.Headers.ContentLength is 0) { return string.Empty; }
        await using Stream body = await response.Content.ReadAsStreamAsync(cancellationToken).ConfigureAwait(false);
        using JsonDocument document = await JsonDocument.ParseAsync(body, cancellationToken: cancellationToken).ConfigureAwait(false);
        return document.RootElement.TryGetProperty("id", out JsonElement id) ? id.GetString() ?? string.Empty : string.Empty;
    }
}
