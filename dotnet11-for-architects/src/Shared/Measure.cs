using System.Diagnostics;

namespace Dotnet11Sample;

public static class Measure
{
    /// <summary>Median wall time in milliseconds over <paramref name="runs"/> runs, after two warm-up runs.</summary>
    public static double MedianMilliseconds(Action action, int runs = 7)
    {
        action();
        action();
        double[] samples = new double[runs];
        for (int i = 0; i < runs; i++)
        {
            long started = Stopwatch.GetTimestamp();
            action();
            samples[i] = Stopwatch.GetElapsedTime(started).TotalMilliseconds;
        }

        Array.Sort(samples);
        return Math.Round(samples[runs / 2], 2);
    }
}
