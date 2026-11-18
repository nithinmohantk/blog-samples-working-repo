// The handler on its own, with no Lambda runtime and no container: dotnet run --project tests/SelfTest -c Release
using System.Text.Json;
using Amazon.Lambda.APIGatewayEvents;
using Quotes;

int passed = 0, failed = 0;
void Check(string name, bool condition, string detail = "")
{
    if (condition) { passed++; } else { failed++; }
    Console.WriteLine($"{(condition ? "ok  " : "FAIL")}  {name}{(condition || detail.Length == 0 ? "" : $"  [{detail}]")}");
}

QuoteHandler handler = new();
APIGatewayHttpApiV2ProxyResponse Ask(string? body) => handler.Handle(new APIGatewayHttpApiV2ProxyRequest { Body = body }, null!);
JsonElement Json(APIGatewayHttpApiV2ProxyResponse response) => JsonDocument.Parse(response.Body).RootElement;

APIGatewayHttpApiV2ProxyResponse quote = Ask("""{"sku":"SKU-00042","quantity":3,"country":"IE"}""");
Check("a quote for three units in Ireland is priced and taxed at 23%", quote.StatusCode == 200 && Json(quote).GetProperty("unitPrice").GetDecimal() == 332.98m
    && Json(quote).GetProperty("net").GetDecimal() == 998.94m && Json(quote).GetProperty("tax").GetDecimal() == 229.76m && Json(quote).GetProperty("total").GetDecimal() == 1228.70m, quote.Body);
Check("the body is camelCase JSON with a content type", quote.Body.StartsWith("""{"sku":"SKU-00042","quantity":3,"unitPrice":""") && quote.Headers["content-type"] == "application/json", quote.Body);
Check("an unknown country is quoted without tax", Json(Ask("""{"sku":"SKU-00042","quantity":1,"country":"US"}""")).GetProperty("tax").GetDecimal() == 0m);
Check("property names are matched whatever their case", Ask("""{"SKU":"SKU-00042","Quantity":1}""").StatusCode == 200);
Check("an unknown product is 404", Ask("""{"sku":"NOPE","quantity":1}""").StatusCode == 404);
Check("no body, a quantity of zero, and text that is not JSON are each 400", Ask(null).StatusCode == 400 && Ask("""{"sku":"SKU-00042","quantity":0}""").StatusCode == 400 && Ask("{not json").StatusCode == 400);
Check("the catalogue is the same in every build: first, middle and last prices", Json(Ask("""{"sku":"SKU-00001","quantity":1}""")).GetProperty("unitPrice").GetDecimal() == 80.19m
    && Json(Ask("""{"sku":"SKU-25000","quantity":1}""")).GetProperty("unitPrice").GetDecimal() == 218.00m && Json(Ask("""{"sku":"SKU-50000","quantity":1}""")).GetProperty("unitPrice").GetDecimal() == 435.00m,
    $"{Ask("""{"sku":"SKU-00001","quantity":1}""").Body} {Ask("""{"sku":"SKU-25000","quantity":1}""").Body} {Ask("""{"sku":"SKU-50000","quantity":1}""").Body}");

// What the two SnapStart hooks do, called directly. Whether Lambda calls them is not something a test here can show.
string before = handler.InstanceId;
handler.Warm();
Check("warming runs a request and leaves the instance as it was", handler.InstanceId == before && handler.Handled > 0);
handler.BecomeANewInstance();
Check("after a restore the instance has a new identity and a clean count", handler.InstanceId != before && handler.Handled == 0);
Check("responses carry the identity of the instance that produced them", Ask("""{"sku":"SKU-00042","quantity":1}""").Headers["x-instance"] == handler.InstanceId);

Console.WriteLine($"\n{passed} of {passed + failed} checks passed");
return failed == 0 ? 0 : 1;
