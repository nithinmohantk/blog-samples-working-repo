using FhirEvents.Core;
using Npgsql;

namespace FhirEvents.Functions;

public sealed class PostgresProjectionStore(NpgsqlDataSource database) : IProjectionStore
{
    public async Task EnsureSchemaAsync(CancellationToken cancellationToken)
    {
        await using NpgsqlCommand command = database.CreateCommand("""
            CREATE TABLE IF NOT EXISTS bp_projection (
                resource_type text    NOT NULL,
                resource_id   text    NOT NULL,
                version       bigint  NOT NULL,
                deleted       boolean NOT NULL,
                retracted     boolean NOT NULL,
                patient_id    text,
                effective     text,
                systolic      numeric,
                diastolic     numeric,
                processed_at  timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (resource_type, resource_id)
            )
            """);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task<ProjectionRow?> GetAsync(string resourceType, string resourceId, CancellationToken cancellationToken)
    {
        await using NpgsqlCommand command = database.CreateCommand("""
            SELECT version, deleted, retracted, patient_id, effective, systolic, diastolic
            FROM bp_projection WHERE resource_type = $1 AND resource_id = $2
            """);
        command.Parameters.AddWithValue(resourceType);
        command.Parameters.AddWithValue(resourceId);
        await using NpgsqlDataReader reader = await command.ExecuteReaderAsync(cancellationToken);
        if (!await reader.ReadAsync(cancellationToken))
        {
            return null;
        }

        return new ProjectionRow(resourceType, resourceId, reader.GetInt64(0), reader.GetBoolean(1), reader.GetBoolean(2),
            reader.IsDBNull(3) ? null : reader.GetString(3),
            reader.IsDBNull(4) ? null : reader.GetString(4),
            reader.IsDBNull(5) ? null : reader.GetDecimal(5),
            reader.IsDBNull(6) ? null : reader.GetDecimal(6));
    }

    /// <summary>
    /// One statement decides and writes. The WHERE clause on the conflict branch is what makes a duplicate
    /// or a late delivery a no-op, even when two instances process the same resource at the same moment.
    /// </summary>
    public async Task<bool> UpsertIfNewerAsync(ProjectionRow row, CancellationToken cancellationToken)
    {
        await using NpgsqlCommand command = database.CreateCommand("""
            INSERT INTO bp_projection
                (resource_type, resource_id, version, deleted, retracted, patient_id, effective, systolic, diastolic)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (resource_type, resource_id) DO UPDATE SET
                version = EXCLUDED.version, deleted = EXCLUDED.deleted, retracted = EXCLUDED.retracted,
                patient_id = EXCLUDED.patient_id, effective = EXCLUDED.effective,
                systolic = EXCLUDED.systolic, diastolic = EXCLUDED.diastolic, processed_at = now()
            WHERE bp_projection.version < EXCLUDED.version
            """);
        command.Parameters.AddWithValue(row.ResourceType);
        command.Parameters.AddWithValue(row.ResourceId);
        command.Parameters.AddWithValue(row.Version);
        command.Parameters.AddWithValue(row.Deleted);
        command.Parameters.AddWithValue(row.Retracted);
        command.Parameters.AddWithValue((object?)row.PatientId ?? DBNull.Value);
        command.Parameters.AddWithValue((object?)row.Effective ?? DBNull.Value);
        command.Parameters.AddWithValue((object?)row.Systolic ?? DBNull.Value);
        command.Parameters.AddWithValue((object?)row.Diastolic ?? DBNull.Value);
        return await command.ExecuteNonQueryAsync(cancellationToken) == 1;
    }
}
