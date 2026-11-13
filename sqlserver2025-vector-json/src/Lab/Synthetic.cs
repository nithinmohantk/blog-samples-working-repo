using System.Globalization;
using System.Text;

namespace Lab;

/// <summary>
/// Repeatable test data. The vectors are not embeddings from a model: they are points scattered around 64 centres
/// on the unit sphere, which gives nearest-neighbour search something with structure to find.
/// </summary>
public sealed class Synthetic(ulong seed)
{
    private ulong _state = seed;

    public static readonly string[] Countries = ["IE", "GB", "DE", "FR", "NL", "ES", "IT", "PL", "SE", "DK", "BE", "PT", "AT", "FI", "CZ", "MT"];

    public float[][] Vectors(int count, int dimensions, int clusters, double noise, out int[] cluster)
    {
        float[][] centres = [.. Enumerable.Range(0, clusters).Select(_ => Unit(dimensions, null, 0))];
        float[][] vectors = new float[count][];
        cluster = new int[count];
        for (int i = 0; i < count; i++)
        {
            cluster[i] = (int)(Next() % (ulong)clusters);
            vectors[i] = Unit(dimensions, centres[cluster[i]], noise);
        }
        return vectors;
    }

    /// <summary>A unit vector near an existing one, used as a query.</summary>
    public float[] Near(float[] vector, double noise) => Unit(vector.Length, vector, noise);

    public int Pick(int below) => (int)(Next() % (ulong)below);

    /// <summary>An order document of about 400 bytes. One country in sixteen, MT, is rare: about 1 order in 200.</summary>
    public string Order(int id)
    {
        string country = Pick(200) == 0 ? "MT" : Countries[Pick(Countries.Length - 1)];
        int lines = 1 + Pick(4);
        decimal total = 0;
        StringBuilder json = new();
        json.Append(CultureInfo.InvariantCulture, $"{{\"orderId\":{id},\"status\":\"new\",\"customer\":{{\"id\":{1000 + Pick(9000)},\"country\":\"{country}\"}},\"lines\":[");
        for (int line = 0; line < lines; line++)
        {
            int quantity = 1 + Pick(5);
            decimal price = (100 + Pick(9900)) / 100m;
            total += quantity * price;
            json.Append(CultureInfo.InvariantCulture, $"{(line == 0 ? "" : ",")}{{\"sku\":\"SKU-{Pick(50000):D5}\",\"qty\":{quantity},\"price\":{price:F2}}}");
        }
        json.Append(CultureInfo.InvariantCulture, $"],\"total\":{total:F2},\"placed\":\"2026-03-{1 + Pick(28):D2}T{Pick(24):D2}:{Pick(60):D2}:00Z\",\"notes\":\"Leave with reception if nobody answers the door, order {id}\"}}");
        return json.ToString();
    }

    public static string Json(float[] vector)
    {
        StringBuilder json = new("[", vector.Length * 12);
        for (int i = 0; i < vector.Length; i++)
        {
            json.Append(i == 0 ? "" : ",").Append(vector[i].ToString("R", CultureInfo.InvariantCulture));
        }
        return json.Append(']').ToString();
    }

    public static double CosineDistance(float[] a, float[] b)
    {
        double dot = 0, normA = 0, normB = 0;
        for (int i = 0; i < a.Length; i++)
        {
            dot += (double)a[i] * b[i];
            normA += (double)a[i] * a[i];
            normB += (double)b[i] * b[i];
        }
        return 1 - dot / (Math.Sqrt(normA) * Math.Sqrt(normB));
    }

    private float[] Unit(int dimensions, float[]? around, double noise)
    {
        double[] values = new double[dimensions];
        double length = 0;
        for (int i = 0; i < dimensions; i++)
        {
            values[i] = around is null ? Gaussian() : around[i] + noise * Gaussian() / Math.Sqrt(dimensions);
            length += values[i] * values[i];
        }
        length = Math.Sqrt(length);
        return [.. values.Select(value => (float)(value / length))];
    }

    private double Gaussian()
    {
        double u1 = 1.0 - Uniform(), u2 = Uniform();
        return Math.Sqrt(-2.0 * Math.Log(u1)) * Math.Cos(2.0 * Math.PI * u2);
    }

    private double Uniform() => (Next() >> 11) * (1.0 / (1UL << 53));

    private ulong Next()
    {
        // SplitMix64: small, fast and the same on every machine.
        ulong z = _state += 0x9E3779B97F4A7C15UL;
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
        z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
        return z ^ (z >> 31);
    }
}
