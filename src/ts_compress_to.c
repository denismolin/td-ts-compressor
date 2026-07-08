/*
 * ts_compress_to.c
 *
 * Teradata C SQLTable table operator for time-series compression.
 *
 * The operator buffers one ordered input stream, runs a geometric
 * compression pass, and writes only selected input rows plus metadata:
 *
 *   compression_importance INTEGER
 *   compression_distance   FLOAT
 *
 * This implementation uses the order/time column as the x-axis. Numeric
 * sequence values are used directly, preserving irregular gaps. Date and
 * timestamp values are converted to elapsed units from the first point in
 * the partition.
 *
 * By default, tol_x and tol_y are computed automatically as curve units per
 * pixel for a 16:9 plot. The full x range is mapped to 95% of the configured
 * plot width, and the y range is mapped to the configured plot height.
 */

#define SQL_TEXT Latin_Text

#include <math.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sqltypes_td.h"

#define CONTRACT_SUCCESS   1
#define CONTRACT_FAILURE  -1
#define IS_NULL           -1
#define IS_NOT_NULL        0

#define DEFAULT_N_MAX          -1
#define DEFAULT_DISTANCE_MAX    1.0
#define DEFAULT_MIN_RELATIVE_GAIN  0.05
#define DEFAULT_MIN_ABSOLUTE_GAIN  0.25
#define DEFAULT_AUTO_NMAX_LOG_DROP 1.5
#define DEFAULT_TOL_X           1.0
#define DEFAULT_TOL_Y           1.0
#define DEFAULT_PLOT_WIDTH_PX   1600.0
#define DEFAULT_PLOT_HEIGHT_PX   900.0
#define DEFAULT_PLOT_X_FRACTION    0.95
#define MIN_TOLERANCE             1.0e-12
#define CUSTOM_PARAM_BUFFER_SIZE 128
#define COMPACT_CHUNK_SIZE 262144

#define TIME_TYPE_AUTO       0
#define TIME_TYPE_NUMERIC    1
#define TIME_TYPE_DATE       2
#define TIME_TYPE_TIMESTAMP  3

typedef struct AttributeValue
{
    char *data;
    int null_ind;
    int length;
} AttributeValue;

typedef struct BufferedRow
{
    AttributeValue *attrs;
    double x;
    double y;
    long long raw_time_bigint;
    double raw_y;
    int selected;
    int importance;
    double distance;
} BufferedRow;

typedef struct CompactRow
{
    double x;
    double y;
    float distance;
    short importance;
    unsigned char selected;
} CompactRow;

typedef struct CompactBuffer
{
    CompactRow **chunks;
    int chunk_count;
    int chunk_capacity;
} CompactBuffer;

typedef struct PartitionId
{
    char *data;
    int null_ind;
    int length;
} PartitionId;

typedef struct PartitionIds
{
    PartitionId *ids;
    int count;
    int captured;
} PartitionIds;

typedef struct CompressionParams
{
    int n_max;
    int n_max_auto;
    double distance_max;
    double min_relative_gain;
    double min_absolute_gain;
    double auto_log_drop;
    double tol_x;
    double tol_y;
    int auto_tol_x;
    int auto_tol_y;
    double plot_width_px;
    double plot_height_px;
    double plot_x_fraction;
    double time_unit_seconds;
    int time_type;
    int time_col_ndx;
    int value_col_ndx;
    int id_col_count;
    double norm_base_x;
    double norm_min_x;
    double norm_min_y;
} CompressionParams;

static void init_params(CompressionParams *params)
{
    params->n_max = DEFAULT_N_MAX;
    params->n_max_auto = 0;
    params->distance_max = DEFAULT_DISTANCE_MAX;
    params->min_relative_gain = DEFAULT_MIN_RELATIVE_GAIN;
    params->min_absolute_gain = DEFAULT_MIN_ABSOLUTE_GAIN;
    params->auto_log_drop = DEFAULT_AUTO_NMAX_LOG_DROP;
    params->tol_x = DEFAULT_TOL_X;
    params->tol_y = DEFAULT_TOL_Y;
    params->auto_tol_x = 1;
    params->auto_tol_y = 1;
    params->plot_width_px = DEFAULT_PLOT_WIDTH_PX;
    params->plot_height_px = DEFAULT_PLOT_HEIGHT_PX;
    params->plot_x_fraction = DEFAULT_PLOT_X_FRACTION;
    params->time_unit_seconds = 1.0;
    params->time_type = TIME_TYPE_AUTO;
    params->time_col_ndx = 2;
    params->value_col_ndx = 3;
    params->id_col_count = 1;
    params->norm_base_x = 0.0;
    params->norm_min_x = 0.0;
    params->norm_min_y = 0.0;
}

static void trim_text(char *text)
{
    char *start;
    char *end;
    int len;

    if (text == NULL || text[0] == '\0')
    {
        return;
    }

    start = text;
    while (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r')
    {
        start++;
    }

    if (start != text)
    {
        memmove(text, start, strlen(start) + 1);
    }

    len = (int)strlen(text);
    if (len <= 0)
    {
        return;
    }

    end = text + len - 1;
    while (end >= text &&
           (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r'))
    {
        *end = '\0';
        end--;
    }
}

static int key_equals_ignore_case(
    const void *raw_key,
    int raw_key_size,
    const char *key
);

static int read_custom_param_text(
    const char *key,
    char *buffer,
    int buffer_size
)
{
    Key_info_t key_info;
    Values_t *allocated_values = NULL;
    void *value_ptr = NULL;
    int copy_len;
    int key_count;
    int key_ndx;
    int found_value = 0;

    if (key == NULL || buffer == NULL || buffer_size <= 1)
    {
        return 0;
    }

    buffer[0] = '\0';

    key_count = FNC_TblOpGetCustomKeyCount();
    for (key_ndx = 0; key_ndx < key_count; key_ndx++)
    {
        memset(&key_info, 0, sizeof(Key_info_t));
        if (FNC_TblOpGetCustomKeyInfoAt(key_ndx, &key_info) != TBLOP_SUCCESS)
        {
            continue;
        }

        if (key_equals_ignore_case(key_info.key, key_info.keySize, key))
        {
            break;
        }
    }

    if (key_ndx >= key_count)
    {
        return 0;
    }

    if (key_info.numOfVal <= 0)
    {
        return 0;
    }

    if (key_info.values_r == NULL)
    {
        allocated_values = (Values_t *)FNC_malloc(
            sizeof(Values_t) * key_info.numOfVal
        );
        if (allocated_values == NULL)
        {
            return 0;
        }

        memset(allocated_values, 0, sizeof(Values_t) * key_info.numOfVal);
        key_info.values_r = allocated_values;
    }

    if (FNC_TblOpGetCustomValuesOf(&key_info) != TBLOP_SUCCESS)
    {
        if (allocated_values != NULL)
        {
            FNC_free(allocated_values);
        }
        return 0;
    }

    if (key_info.values_r == NULL || key_info.values_r[0].value == NULL)
    {
        if (allocated_values != NULL)
        {
            FNC_free(allocated_values);
        }
        return 0;
    }

    value_ptr = key_info.values_r[0].value;
    copy_len = key_info.valType.size.length;
    if (copy_len <= 0 || copy_len >= buffer_size)
    {
        copy_len = buffer_size - 1;
    }

    memcpy(buffer, value_ptr, copy_len);
    buffer[copy_len] = '\0';
    found_value = 1;

    if (allocated_values != NULL)
    {
        FNC_free(allocated_values);
    }

    trim_text(buffer);
    return found_value && buffer[0] != '\0';
}

static int text_equals_ignore_case(const char *left, const char *right)
{
    int i = 0;

    if (left == NULL || right == NULL)
    {
        return 0;
    }

    while (left[i] != '\0' && right[i] != '\0')
    {
        char l = left[i];
        char r = right[i];

        if (l >= 'a' && l <= 'z')
        {
            l = (char)(l - ('a' - 'A'));
        }

        if (r >= 'a' && r <= 'z')
        {
            r = (char)(r - ('a' - 'A'));
        }

        if (l != r)
        {
            return 0;
        }

        i++;
    }

    return left[i] == '\0' && right[i] == '\0';
}

static int key_equals_ignore_case(const void *raw_key, int raw_key_size, const char *key)
{
    const char *left = (const char *)raw_key;
    int key_len;
    int i;

    if (left == NULL || key == NULL)
    {
        return 0;
    }

    if (raw_key_size <= 0 || raw_key_size > 64)
    {
        return 0;
    }

    key_len = (int)strlen(key);
    while (raw_key_size > 0 &&
           (left[raw_key_size - 1] == ' ' ||
            left[raw_key_size - 1] == '\0' ||
            left[raw_key_size - 1] == '\t' ||
            left[raw_key_size - 1] == '\r' ||
            left[raw_key_size - 1] == '\n'))
    {
        raw_key_size--;
    }

    if (raw_key_size != key_len)
    {
        return 0;
    }

    for (i = 0; i < raw_key_size; i++)
    {
        char l = left[i];
        char r = key[i];

        if (l >= 'a' && l <= 'z')
        {
            l = (char)(l - ('a' - 'A'));
        }

        if (r >= 'a' && r <= 'z')
        {
            r = (char)(r - ('a' - 'A'));
        }

        if (l != r)
        {
            return 0;
        }
    }

    return 1;
}

static int is_auto_text(const char *text)
{
    return text == NULL ||
           text[0] == '\0' ||
           text_equals_ignore_case(text, "auto") ||
           text_equals_ignore_case(text, "default");
}

static double finite_or_default(double value, double default_value)
{
    if (!isfinite(value))
    {
        return default_value;
    }

    return value;
}

static int parse_fixed_digits(const char *text, int start, int count, int *value)
{
    int i;
    int parsed = 0;

    if (text == NULL || value == NULL)
    {
        return 0;
    }

    for (i = 0; i < count; i++)
    {
        char c = text[start + i];
        if (c < '0' || c > '9')
        {
            return 0;
        }
        parsed = (parsed * 10) + (c - '0');
    }

    *value = parsed;
    return 1;
}

static long long days_from_civil(int year, int month, int day)
{
    int era;
    unsigned int yoe;
    unsigned int doy;
    unsigned int doe;

    year -= month <= 2;
    era = (year >= 0 ? year : year - 399) / 400;
    yoe = (unsigned int)(year - era * 400);
    doy = (unsigned int)((153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 +
                         day - 1);
    doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;

    return (long long)(era * 146097 + (int)doe - 719468);
}

static int is_leap_year(int year)
{
    return (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0);
}

static int days_in_month(int year, int month)
{
    static const int days_by_month[12] =
    {
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    };

    if (month < 1 || month > 12)
    {
        return 0;
    }

    if (month == 2 && is_leap_year(year))
    {
        return 29;
    }

    return days_by_month[month - 1];
}

static int parse_timestamp_text_to_seconds(const char *text, double *seconds)
{
    int year;
    int month;
    int day;
    int hour = 0;
    int minute = 0;
    int second = 0;
    int offset_sign = 0;
    int offset_hour = 0;
    int offset_minute = 0;
    int i;
    double fraction = 0.0;
    double divisor = 10.0;
    double total_seconds;

    if (text == NULL || seconds == NULL)
    {
        return 0;
    }

    if (!parse_fixed_digits(text, 0, 4, &year) ||
        text[4] != '-' ||
        !parse_fixed_digits(text, 5, 2, &month) ||
        text[7] != '-' ||
        !parse_fixed_digits(text, 8, 2, &day))
    {
        return 0;
    }

    if (month < 1 ||
        month > 12 ||
        day < 1 ||
        day > days_in_month(year, month))
    {
        return 0;
    }

    if (text[10] == ' ' || text[10] == 'T')
    {
        if (!parse_fixed_digits(text, 11, 2, &hour) ||
            text[13] != ':' ||
            !parse_fixed_digits(text, 14, 2, &minute) ||
            text[16] != ':' ||
            !parse_fixed_digits(text, 17, 2, &second))
        {
            return 0;
        }

        i = 19;
        if (text[i] == '.')
        {
            i++;
            while (text[i] >= '0' && text[i] <= '9')
            {
                fraction += ((double)(text[i] - '0')) / divisor;
                divisor *= 10.0;
                i++;
            }
        }

        if (text[i] == '+' || text[i] == '-')
        {
            offset_sign = (text[i] == '+') ? 1 : -1;
            if (parse_fixed_digits(text, i + 1, 2, &offset_hour))
            {
                if (text[i + 3] == ':')
                {
                    (void)parse_fixed_digits(text, i + 4, 2, &offset_minute);
                }
                else
                {
                    (void)parse_fixed_digits(text, i + 3, 2, &offset_minute);
                }
            }
        }
    }

    total_seconds = ((double)days_from_civil(year, month, day)) * 86400.0 +
                    ((double)hour) * 3600.0 +
                    ((double)minute) * 60.0 +
                    ((double)second) +
                    fraction;

    if (offset_sign != 0)
    {
        total_seconds -= (double)offset_sign *
                         (((double)offset_hour) * 3600.0 +
                          ((double)offset_minute) * 60.0);
    }

    *seconds = total_seconds;
    return 1;
}

static int decode_teradata_date_to_seconds(int encoded_date, double *seconds)
{
    int year;
    int month;
    int day;

    if (seconds == NULL)
    {
        return 0;
    }

    year = encoded_date / 10000 + 1900;
    month = (encoded_date / 100) % 100;
    day = encoded_date % 100;

    if (year < 1 ||
        month < 1 ||
        month > 12 ||
        day < 1 ||
        day > days_in_month(year, month))
    {
        return 0;
    }

    *seconds = ((double)days_from_civil(year, month, day)) * 86400.0;
    return 1;
}

static void read_custom_int_param(const char *key, int *target)
{
    char text[CUSTOM_PARAM_BUFFER_SIZE];
    char *end = NULL;
    long parsed;

    if (!read_custom_param_text(key, text, CUSTOM_PARAM_BUFFER_SIZE))
    {
        return;
    }

    parsed = strtol(text, &end, 10);
    if (end != text &&
        (parsed == -1 || (parsed >= 0 && parsed <= INT_MAX)))
    {
        *target = (int)parsed;
    }
}

static void read_custom_n_max_param(CompressionParams *params)
{
    char text[CUSTOM_PARAM_BUFFER_SIZE];
    char *end = NULL;
    long parsed;

    if (!read_custom_param_text("n_max", text, CUSTOM_PARAM_BUFFER_SIZE))
    {
        return;
    }

    if (is_auto_text(text))
    {
        params->n_max = -1;
        params->n_max_auto = 1;
        return;
    }

    parsed = strtol(text, &end, 10);
    if (end != text &&
        (parsed == -1 || (parsed > 0 && parsed <= INT_MAX)))
    {
        params->n_max = (int)parsed;
        params->n_max_auto = 0;
    }
}

static void read_custom_double_param(
    const char *key,
    double *target,
    int require_positive
)
{
    char text[CUSTOM_PARAM_BUFFER_SIZE];
    char *end = NULL;
    double parsed;

    if (!read_custom_param_text(key, text, CUSTOM_PARAM_BUFFER_SIZE))
    {
        return;
    }

    parsed = strtod(text, &end);
    if (end == text)
    {
        return;
    }

    if (require_positive && parsed <= 0.0)
    {
        return;
    }

    if (!require_positive && parsed < -1.0)
    {
        return;
    }

    *target = parsed;
}

static void read_custom_tolerance_param(
    const char *key,
    double *target,
    int *auto_flag
)
{
    char text[CUSTOM_PARAM_BUFFER_SIZE];
    char *end = NULL;
    double parsed;

    if (!read_custom_param_text(key, text, CUSTOM_PARAM_BUFFER_SIZE))
    {
        return;
    }

    if (is_auto_text(text))
    {
        *auto_flag = 1;
        return;
    }

    parsed = strtod(text, &end);
    if (end != text && parsed > MIN_TOLERANCE)
    {
        *target = parsed;
        *auto_flag = 0;
    }
}

static void read_custom_time_unit_param(CompressionParams *params)
{
    char text[CUSTOM_PARAM_BUFFER_SIZE];

    if (!read_custom_param_text("time_unit", text, CUSTOM_PARAM_BUFFER_SIZE))
    {
        return;
    }

    if (text_equals_ignore_case(text, "microsecond") ||
        text_equals_ignore_case(text, "microseconds") ||
        text_equals_ignore_case(text, "us"))
    {
        params->time_unit_seconds = 0.000001;
    }
    else if (text_equals_ignore_case(text, "millisecond") ||
             text_equals_ignore_case(text, "milliseconds") ||
             text_equals_ignore_case(text, "ms"))
    {
        params->time_unit_seconds = 0.001;
    }
    else if (text_equals_ignore_case(text, "second") ||
             text_equals_ignore_case(text, "seconds") ||
             text_equals_ignore_case(text, "s"))
    {
        params->time_unit_seconds = 1.0;
    }
    else if (text_equals_ignore_case(text, "minute") ||
             text_equals_ignore_case(text, "minutes") ||
             text_equals_ignore_case(text, "min"))
    {
        params->time_unit_seconds = 60.0;
    }
    else if (text_equals_ignore_case(text, "hour") ||
             text_equals_ignore_case(text, "hours") ||
             text_equals_ignore_case(text, "h"))
    {
        params->time_unit_seconds = 3600.0;
    }
    else if (text_equals_ignore_case(text, "day") ||
             text_equals_ignore_case(text, "days") ||
             text_equals_ignore_case(text, "d"))
    {
        params->time_unit_seconds = 86400.0;
    }
}

static void read_custom_time_type_param(CompressionParams *params)
{
    char text[CUSTOM_PARAM_BUFFER_SIZE];

    if (!read_custom_param_text("time_type", text, CUSTOM_PARAM_BUFFER_SIZE))
    {
        return;
    }

    if (text_equals_ignore_case(text, "auto") ||
        text_equals_ignore_case(text, "default"))
    {
        params->time_type = TIME_TYPE_AUTO;
    }
    else if (text_equals_ignore_case(text, "numeric") ||
             text_equals_ignore_case(text, "number") ||
             text_equals_ignore_case(text, "sequence") ||
             text_equals_ignore_case(text, "seq"))
    {
        params->time_type = TIME_TYPE_NUMERIC;
    }
    else if (text_equals_ignore_case(text, "date"))
    {
        params->time_type = TIME_TYPE_DATE;
    }
    else if (text_equals_ignore_case(text, "timestamp") ||
             text_equals_ignore_case(text, "tstz") ||
             text_equals_ignore_case(text, "datetime"))
    {
        params->time_type = TIME_TYPE_TIMESTAMP;
    }
}

static void load_custom_params(CompressionParams *params)
{
    read_custom_n_max_param(params);
    read_custom_int_param("id_column_count", &(params->id_col_count));
    read_custom_int_param("time_column_index", &(params->time_col_ndx));
    read_custom_int_param("value_column_index", &(params->value_col_ndx));
    read_custom_double_param("distance_max", &(params->distance_max), 0);
    read_custom_double_param(
        "min_relative_gain",
        &(params->min_relative_gain),
        1
    );
    read_custom_double_param(
        "min_absolute_gain",
        &(params->min_absolute_gain),
        1
    );
    read_custom_double_param(
        "auto_log_drop",
        &(params->auto_log_drop),
        1
    );
    read_custom_tolerance_param(
        "tol_x",
        &(params->tol_x),
        &(params->auto_tol_x)
    );
    read_custom_tolerance_param(
        "tol_y",
        &(params->tol_y),
        &(params->auto_tol_y)
    );
    read_custom_double_param("plot_width_px", &(params->plot_width_px), 1);
    read_custom_double_param("plot_height_px", &(params->plot_height_px), 1);
    read_custom_double_param(
        "plot_x_fraction",
        &(params->plot_x_fraction),
        1
    );

    if (params->plot_x_fraction > 1.0)
    {
        params->plot_x_fraction = 1.0;
    }

    if (params->min_relative_gain > 1.0)
    {
        params->min_relative_gain = 1.0;
    }

    read_custom_time_unit_param(params);
    read_custom_time_type_param(params);
}

/*
 * Contract function.
 *
 * The tested identity operator uses a schema-preserving dynamic contract.
 * For this compression operator, notebooks register fixed output schemas
 * matching the input columns plus the two metadata columns, so the runtime
 * can be reused across BIGINT, TIMESTAMP, and TIMESTAMP WITH TIME ZONE demos.
 */
void ts_compress_to_contract(
    INTEGER *result,
    int *indicator_Result,
    char sqlstate[6],
    SQL_TEXT extname[129],
    SQL_TEXT specific_name[129],
    SQL_TEXT error_message[257]
)
{
    int incount = 0;
    int outcount = 0;
    int input_col_count = 0;
    int coldef_size = 0;

    FNC_TblOpColumnDef_t *iCols = NULL;
    FNC_TblOpColumnDef_t *oCols = NULL;

    (void)extname;
    (void)specific_name;

    *result = CONTRACT_FAILURE;
    *indicator_Result = IS_NOT_NULL;
    strcpy(sqlstate, "00000");

    FNC_TblOpGetStreamCount(&incount, &outcount);

    if (incount != 1)
    {
        strcpy(sqlstate, "U0001");
        strcpy((char *)error_message,
               "ts_compress_to requires exactly one input stream.");
        goto cleanup;
    }

    input_col_count = FNC_TblOpGetColCount(0, ISINPUT);

    if (input_col_count <= 0)
    {
        strcpy(sqlstate, "U0002");
        strcpy((char *)error_message,
               "ts_compress_to input stream has no columns.");
        goto cleanup;
    }

    coldef_size = TblOpSIZECOLDEF(input_col_count);

    iCols = (FNC_TblOpColumnDef_t *)FNC_malloc(coldef_size);
    oCols = (FNC_TblOpColumnDef_t *)FNC_malloc(coldef_size);

    if (iCols == NULL || oCols == NULL)
    {
        strcpy(sqlstate, "U0003");
        strcpy((char *)error_message,
               "Could not allocate column definition structures.");
        goto cleanup;
    }

    memset(iCols, 0, coldef_size);
    memset(oCols, 0, coldef_size);
    TblOpINITCOLDEF(iCols, input_col_count);
    TblOpINITCOLDEF(oCols, input_col_count);

    FNC_TblOpGetColDef(0, ISINPUT, iCols);
    memcpy(oCols, iCols, coldef_size);
    FNC_TblOpSetOutputColDef(0, oCols);

    *result = CONTRACT_SUCCESS;
    *indicator_Result = IS_NOT_NULL;
    strcpy(sqlstate, "00000");

cleanup:
    if (oCols != NULL)
    {
        FNC_free(oCols);
    }

    if (iCols != NULL)
    {
        FNC_free(iCols);
    }
}

static void free_buffered_row(BufferedRow *row, int column_count)
{
    int j;

    if (row == NULL)
    {
        return;
    }

    if (row->attrs == NULL)
    {
        return;
    }

    for (j = 0; j < column_count; j++)
    {
        if (row->attrs[j].data != NULL)
        {
            FNC_free(row->attrs[j].data);
            row->attrs[j].data = NULL;
        }
    }
    FNC_free(row->attrs);
    row->attrs = NULL;
}

static void free_buffered_rows(BufferedRow *rows, int row_count, int column_count)
{
    int i;

    if (rows == NULL)
    {
        return;
    }

    for (i = 0; i < row_count; i++)
    {
        free_buffered_row(&rows[i], column_count);
    }

    FNC_free(rows);
}

static int ensure_capacity(BufferedRow **rows, int *capacity, int needed)
{
    BufferedRow *new_rows;
    int new_capacity;
    int old_capacity;

    if (needed <= *capacity)
    {
        return 1;
    }

    old_capacity = *capacity;
    new_capacity = (*capacity == 0) ? 1024 : (*capacity * 2);

    while (new_capacity < needed)
    {
        new_capacity *= 2;
    }

    new_rows = (BufferedRow *)FNC_malloc(sizeof(BufferedRow) * new_capacity);
    if (new_rows == NULL)
    {
        return 0;
    }

    memset(new_rows, 0, sizeof(BufferedRow) * new_capacity);

    if (*rows != NULL)
    {
        memcpy(new_rows, *rows, sizeof(BufferedRow) * old_capacity);
        FNC_free(*rows);
    }

    *rows = new_rows;
    *capacity = new_capacity;

    return 1;
}

static CompactRow *compact_row_at(CompactBuffer *buffer, int index)
{
    return &(buffer->chunks[index / COMPACT_CHUNK_SIZE][index % COMPACT_CHUNK_SIZE]);
}

static int ensure_compact_capacity(CompactBuffer *buffer, int needed)
{
    int required_chunks;

    if (buffer == NULL)
    {
        return 0;
    }

    required_chunks = (needed + COMPACT_CHUNK_SIZE - 1) / COMPACT_CHUNK_SIZE;

    if (required_chunks > buffer->chunk_capacity)
    {
        CompactRow **new_chunks;
        int new_capacity = (buffer->chunk_capacity == 0) ? 4 : buffer->chunk_capacity * 2;

        while (new_capacity < required_chunks)
        {
            new_capacity *= 2;
        }

        new_chunks = (CompactRow **)FNC_malloc(sizeof(CompactRow *) * new_capacity);
        if (new_chunks == NULL)
        {
            return 0;
        }

        memset(new_chunks, 0, sizeof(CompactRow *) * new_capacity);
        if (buffer->chunks != NULL)
        {
            memcpy(new_chunks, buffer->chunks, sizeof(CompactRow *) * buffer->chunk_capacity);
            FNC_free(buffer->chunks);
        }

        buffer->chunks = new_chunks;
        buffer->chunk_capacity = new_capacity;
    }

    while (buffer->chunk_count < required_chunks)
    {
        CompactRow *chunk = (CompactRow *)FNC_malloc(sizeof(CompactRow) * COMPACT_CHUNK_SIZE);
        if (chunk == NULL)
        {
            return 0;
        }

        memset(chunk, 0, sizeof(CompactRow) * COMPACT_CHUNK_SIZE);
        buffer->chunks[buffer->chunk_count] = chunk;
        buffer->chunk_count++;
    }

    return 1;
}

static void free_compact_rows(CompactBuffer *buffer)
{
    int i;

    if (buffer == NULL)
    {
        return;
    }

    for (i = 0; i < buffer->chunk_count; i++)
    {
        if (buffer->chunks[i] != NULL)
        {
            FNC_free(buffer->chunks[i]);
            buffer->chunks[i] = NULL;
        }
    }

    if (buffer->chunks != NULL)
    {
        FNC_free(buffer->chunks);
        buffer->chunks = NULL;
    }

    buffer->chunk_count = 0;
    buffer->chunk_capacity = 0;
}

static double read_float8_value(FNC_TblOpHandle_t *input_handle, int col_ndx)
{
    void *value_ptr = NULL;
    int null_ind = IS_NULL;
    int length = 0;
    int rc;

    rc = FNC_TblOpGetAttributeByNdx(
        input_handle,
        col_ndx,
        &value_ptr,
        &null_ind,
        &length
    );

    if (rc != TBLOP_SUCCESS || null_ind == IS_NULL || value_ptr == NULL)
    {
        return 0.0;
    }

    return finite_or_default(*((double *)value_ptr), 0.0);
}

static int read_int_value(FNC_TblOpHandle_t *input_handle, int col_ndx, int default_value)
{
    void *value_ptr = NULL;
    int null_ind = IS_NULL;
    int length = 0;
    int rc;

    rc = FNC_TblOpGetAttributeByNdx(
        input_handle,
        col_ndx,
        &value_ptr,
        &null_ind,
        &length
    );

    if (rc != TBLOP_SUCCESS || null_ind == IS_NULL || value_ptr == NULL)
    {
        return default_value;
    }

    if (length == 4)
    {
        return *((int *)value_ptr);
    }

    if (length == 8)
    {
        return (int)(*((long long *)value_ptr));
    }

    if (length == 2)
    {
        return (int)(*((short *)value_ptr));
    }

    return default_value;
}

static double read_x_axis_value(
    FNC_TblOpHandle_t *input_handle,
    int row_ndx,
    const CompressionParams *params
)
{
    void *value_ptr = NULL;
    int null_ind = IS_NULL;
    int length = 0;
    int rc;
    int col_ndx;
    int time_type;

    if (params == NULL)
    {
        return (double)row_ndx;
    }

    col_ndx = params->time_col_ndx;
    time_type = params->time_type;

    rc = FNC_TblOpGetAttributeByNdx(
        input_handle,
        col_ndx,
        &value_ptr,
        &null_ind,
        &length
    );

    if (rc != TBLOP_SUCCESS || null_ind == IS_NULL || value_ptr == NULL)
    {
        return (double)row_ndx;
    }

    if (length >= 10)
    {
        char text[128];
        char *end = NULL;
        double parsed_seconds;
        double parsed_number;
        int copy_len = length;

        if (copy_len >= (int)sizeof(text))
        {
            copy_len = (int)sizeof(text) - 1;
        }

        memcpy(text, value_ptr, copy_len);
        text[copy_len] = '\0';
        trim_text(text);

        if (time_type != TIME_TYPE_NUMERIC &&
            parse_timestamp_text_to_seconds(text, &parsed_seconds))
        {
            return finite_or_default(parsed_seconds, (double)row_ndx);
        }

        parsed_number = strtod(text, &end);
        if (end != text)
        {
            return finite_or_default(parsed_number, (double)row_ndx);
        }
    }

    if (length == 8)
    {
        long long value = *((long long *)value_ptr);
        return finite_or_default((double)value, (double)row_ndx);
    }

    if (length == 4)
    {
        int value = *((int *)value_ptr);
        double parsed_seconds;

        if (time_type != TIME_TYPE_NUMERIC &&
            decode_teradata_date_to_seconds(value, &parsed_seconds))
        {
            return finite_or_default(parsed_seconds, (double)row_ndx);
        }

        return finite_or_default((double)value, (double)row_ndx);
    }

    if (length == 2)
    {
        short value = *((short *)value_ptr);
        return finite_or_default((double)value, (double)row_ndx);
    }

    return (double)row_ndx;
}

static int buffer_current_row(
    FNC_TblOpHandle_t *input_handle,
    BufferedRow *row,
    int column_count,
    int row_ndx,
    const CompressionParams *params
)
{
    int i;
    int rc;

    row->attrs = (AttributeValue *)FNC_malloc(sizeof(AttributeValue) * column_count);
    if (row->attrs == NULL)
    {
        return 0;
    }

    memset(row->attrs, 0, sizeof(AttributeValue) * column_count);

    row->x = read_x_axis_value(input_handle, row_ndx, params);
    row->y = read_float8_value(input_handle, params->value_col_ndx);
    row->selected = 0;
    row->importance = 0;
    row->distance = 0.0;

    for (i = 0; i < column_count; i++)
    {
        void *value_ptr = NULL;
        int null_ind = IS_NULL;
        int length = 0;

        rc = FNC_TblOpGetAttributeByNdx(
            input_handle,
            i,
            &value_ptr,
            &null_ind,
            &length
        );

        if (rc != TBLOP_SUCCESS)
        {
            free_buffered_row(row, column_count);
            return 0;
        }

        row->attrs[i].null_ind = null_ind;
        row->attrs[i].length = length;

        if (null_ind != IS_NULL && length > 0 && value_ptr != NULL)
        {
            row->attrs[i].data = (char *)FNC_malloc(length);
            if (row->attrs[i].data == NULL)
            {
                free_buffered_row(row, column_count);
                return 0;
            }
            memcpy(row->attrs[i].data, value_ptr, length);
        }
    }

    return 1;
}

static void free_partition_id(PartitionId *partition_id)
{
    if (partition_id == NULL)
    {
        return;
    }

    if (partition_id->data != NULL)
    {
        FNC_free(partition_id->data);
        partition_id->data = NULL;
    }

    partition_id->null_ind = IS_NULL;
    partition_id->length = 0;
}

static void free_partition_ids(PartitionIds *partition_ids)
{
    int i;

    if (partition_ids == NULL)
    {
        return;
    }

    if (partition_ids->ids != NULL)
    {
        for (i = 0; i < partition_ids->count; i++)
        {
            free_partition_id(&(partition_ids->ids[i]));
        }
        FNC_free(partition_ids->ids);
        partition_ids->ids = NULL;
    }

    partition_ids->count = 0;
    partition_ids->captured = 0;
}

static int init_partition_ids(PartitionIds *partition_ids, int count)
{
    int i;

    if (partition_ids == NULL || count <= 0)
    {
        return 0;
    }

    partition_ids->ids = (PartitionId *)FNC_malloc(sizeof(PartitionId) * count);
    if (partition_ids->ids == NULL)
    {
        return 0;
    }

    memset(partition_ids->ids, 0, sizeof(PartitionId) * count);
    partition_ids->count = count;
    partition_ids->captured = 0;
    for (i = 0; i < count; i++)
    {
        partition_ids->ids[i].null_ind = IS_NULL;
    }

    return 1;
}

static int capture_partition_ids(
    FNC_TblOpHandle_t *input_handle,
    PartitionIds *partition_ids
)
{
    int i;

    if (partition_ids == NULL || partition_ids->captured)
    {
        return 1;
    }

    for (i = 0; i < partition_ids->count; i++)
    {
        void *value_ptr = NULL;
        int null_ind = IS_NULL;
        int length = 0;
        int rc = FNC_TblOpGetAttributeByNdx(
            input_handle,
            i,
            &value_ptr,
            &null_ind,
            &length
        );

        if (rc != TBLOP_SUCCESS)
        {
            return 0;
        }

        partition_ids->ids[i].null_ind = null_ind;
        partition_ids->ids[i].length = length;

        if (null_ind != IS_NULL && length > 0 && value_ptr != NULL)
        {
            partition_ids->ids[i].data = (char *)FNC_malloc(length);
            if (partition_ids->ids[i].data == NULL)
            {
                return 0;
            }
            memcpy(partition_ids->ids[i].data, value_ptr, length);
        }
    }

    partition_ids->captured = 1;
    return 1;
}

static int buffer_current_row_compact(
    FNC_TblOpHandle_t *input_handle,
    CompactRow *row,
    int row_ndx,
    const CompressionParams *params,
    PartitionIds *partition_ids
)
{
    if (!capture_partition_ids(input_handle, partition_ids))
    {
        return 0;
    }

    row->x = read_x_axis_value(input_handle, row_ndx, params);
    row->y = read_float8_value(input_handle, params->value_col_ndx);
    row->selected = 0;
    row->importance = 0;
    row->distance = 0.0;

    return 1;
}

static void normalize_compact_rows(
    CompactBuffer *rows,
    int row_count,
    CompressionParams *params
)
{
    double min_x;
    double max_x;
    double min_y;
    double max_y;
    double range_x;
    double range_y;
    double effective_width_px;
    double base_x;
    double unit_seconds;
    int i;

    if (rows == NULL || row_count <= 0 || params == NULL)
    {
        return;
    }

    unit_seconds = params->time_unit_seconds;
    if (unit_seconds <= MIN_TOLERANCE)
    {
        unit_seconds = 1.0;
    }

    base_x = compact_row_at(rows, 0)->x;
    for (i = 0; i < row_count; i++)
    {
        CompactRow *row = compact_row_at(rows, i);
        row->x = (row->x - base_x) / unit_seconds;
    }

    min_x = max_x = compact_row_at(rows, 0)->x;
    min_y = max_y = compact_row_at(rows, 0)->y;

    for (i = 1; i < row_count; i++)
    {
        CompactRow *row = compact_row_at(rows, i);
        if (row->x < min_x)
        {
            min_x = row->x;
        }
        if (row->x > max_x)
        {
            max_x = row->x;
        }
        if (row->y < min_y)
        {
            min_y = row->y;
        }
        if (row->y > max_y)
        {
            max_y = row->y;
        }
    }

    params->norm_base_x = base_x;
    params->norm_min_x = min_x;
    params->norm_min_y = min_y;

    range_x = max_x - min_x;
    range_y = max_y - min_y;

    if (params->auto_tol_x)
    {
        effective_width_px = params->plot_width_px * params->plot_x_fraction;
        params->tol_x = (effective_width_px > MIN_TOLERANCE)
            ? range_x / effective_width_px
            : DEFAULT_TOL_X;
        if (params->tol_x <= MIN_TOLERANCE)
        {
            params->tol_x = DEFAULT_TOL_X;
        }
    }

    if (params->auto_tol_y)
    {
        params->tol_y = (params->plot_height_px > MIN_TOLERANCE)
            ? range_y / params->plot_height_px
            : DEFAULT_TOL_Y;
        if (params->tol_y <= MIN_TOLERANCE)
        {
            params->tol_y = DEFAULT_TOL_Y;
        }
    }

    if (params->tol_x <= MIN_TOLERANCE)
    {
        params->tol_x = DEFAULT_TOL_X;
    }

    if (params->tol_y <= MIN_TOLERANCE)
    {
        params->tol_y = DEFAULT_TOL_Y;
    }

    for (i = 0; i < row_count; i++)
    {
        CompactRow *row = compact_row_at(rows, i);
        row->x = (row->x - min_x) / params->tol_x;
        row->y = (row->y - min_y) / params->tol_y;
    }
}

static void normalize_buffered_rows(
    BufferedRow *rows,
    int row_count,
    CompressionParams *params
)
{
    double min_x;
    double max_x;
    double min_y;
    double max_y;
    double range_x;
    double range_y;
    double effective_width_px;
    double base_x;
    double unit_seconds;
    int i;

    if (rows == NULL || row_count <= 0 || params == NULL)
    {
        return;
    }

    unit_seconds = params->time_unit_seconds;
    if (unit_seconds <= MIN_TOLERANCE)
    {
        unit_seconds = 1.0;
    }

    base_x = rows[0].x;
    for (i = 0; i < row_count; i++)
    {
        rows[i].x = (rows[i].x - base_x) / unit_seconds;
    }

    min_x = rows[0].x;
    max_x = rows[0].x;
    min_y = rows[0].y;
    max_y = rows[0].y;

    for (i = 1; i < row_count; i++)
    {
        if (rows[i].x < min_x)
        {
            min_x = rows[i].x;
        }
        if (rows[i].x > max_x)
        {
            max_x = rows[i].x;
        }
        if (rows[i].y < min_y)
        {
            min_y = rows[i].y;
        }
        if (rows[i].y > max_y)
        {
            max_y = rows[i].y;
        }
    }

    range_x = max_x - min_x;
    range_y = max_y - min_y;
    effective_width_px = params->plot_width_px * params->plot_x_fraction;

    if (params->auto_tol_x)
    {
        if (range_x > MIN_TOLERANCE && effective_width_px > MIN_TOLERANCE)
        {
            params->tol_x = range_x / effective_width_px;
        }
        else
        {
            params->tol_x = DEFAULT_TOL_X;
        }
    }

    if (params->auto_tol_y)
    {
        if (range_y > MIN_TOLERANCE &&
            params->plot_height_px > MIN_TOLERANCE)
        {
            params->tol_y = range_y / params->plot_height_px;
        }
        else
        {
            params->tol_y = DEFAULT_TOL_Y;
        }
    }

    if (params->tol_x <= MIN_TOLERANCE)
    {
        params->tol_x = DEFAULT_TOL_X;
    }

    if (params->tol_y <= MIN_TOLERANCE)
    {
        params->tol_y = DEFAULT_TOL_Y;
    }

    for (i = 0; i < row_count; i++)
    {
        rows[i].x = (rows[i].x - min_x) / params->tol_x;
        rows[i].y = (rows[i].y - min_y) / params->tol_y;
    }
}

static double point_segment_distance(
    double px,
    double py,
    double ax,
    double ay,
    double bx,
    double by
)
{
    double dx = bx - ax;
    double dy = by - ay;
    double denom = sqrt(dx * dx + dy * dy);

    if (denom <= 0.0)
    {
        dx = px - ax;
        dy = py - ay;
        return sqrt(dx * dx + dy * dy);
    }

    return fabs((dy * px) - (dx * py) + (bx * ay) - (by * ax)) / denom;
}

static int collect_interval_candidates(
    BufferedRow *rows,
    int row_count,
    int *candidate_indices,
    double *candidate_distances,
    double *max_distance
)
{
    int left = -1;
    int right = -1;
    int i;
    int candidate_count = 0;
    double global_max_distance = -1.0;

    for (i = 0; i < row_count; i++)
    {
        if (rows[i].selected)
        {
            right = i;

            if (left >= 0 && right > left + 1)
            {
                int j;
                int best = -1;
                double best_distance = -1.0;

                for (j = left + 1; j < right; j++)
                {
                    if (!rows[j].selected)
                    {
                        double d = point_segment_distance(
                            rows[j].x,
                            rows[j].y,
                            rows[left].x,
                            rows[left].y,
                            rows[right].x,
                            rows[right].y
                        );

                        if (d > best_distance)
                        {
                            best_distance = d;
                            best = j;
                        }
                    }
                }

                if (best >= 0)
                {
                    candidate_indices[candidate_count] = best;
                    candidate_distances[candidate_count] = best_distance;
                    candidate_count++;

                    if (best_distance > global_max_distance)
                    {
                        global_max_distance = best_distance;
                    }
                }
            }

            left = right;
        }
    }

    *max_distance = global_max_distance;
    return candidate_count;
}

static int count_selected(BufferedRow *rows, int row_count)
{
    int i;
    int count = 0;

    for (i = 0; i < row_count; i++)
    {
        if (rows[i].selected)
        {
            count++;
        }
    }

    return count;
}

static void compress_rows(BufferedRow *rows, int row_count, const CompressionParams *params)
{
    int *candidate_indices = NULL;
    double *candidate_distances = NULL;
    int selected_count;
    int next_importance;
    double initial_max_distance = -1.0;
    double effective_distance_max;

    if (row_count <= 0)
    {
        return;
    }

    rows[0].selected = 1;
    rows[0].importance = 1;
    rows[0].distance = 0.0;

    if (row_count > 1)
    {
        rows[row_count - 1].selected = 1;
        rows[row_count - 1].importance = 2;
        rows[row_count - 1].distance = 0.0;
    }

    selected_count = count_selected(rows, row_count);
    next_importance = selected_count + 1;
    effective_distance_max = params->distance_max;

    candidate_indices = (int *)FNC_malloc(sizeof(int) * row_count);
    candidate_distances = (double *)FNC_malloc(sizeof(double) * row_count);
    if (candidate_indices == NULL || candidate_distances == NULL)
    {
        goto cleanup;
    }

    while (selected_count < row_count)
    {
        double max_distance = 0.0;
        int candidate_count;
        int best_candidate = -1;
        int i;

        candidate_count = collect_interval_candidates(
            rows,
            row_count,
            candidate_indices,
            candidate_distances,
            &max_distance
        );

        if (candidate_count <= 0)
        {
            break;
        }

        if (initial_max_distance < 0.0)
        {
            initial_max_distance = max_distance;
            if (params->n_max_auto && effective_distance_max < 0.0)
            {
                if (initial_max_distance <= MIN_TOLERANCE)
                {
                    break;
                }
                effective_distance_max =
                    initial_max_distance / pow(10.0, params->auto_log_drop);
                if (effective_distance_max < DEFAULT_DISTANCE_MAX)
                {
                    effective_distance_max = DEFAULT_DISTANCE_MAX;
                }
            }
        }

        if (effective_distance_max >= 0.0 && max_distance < effective_distance_max)
        {
            break;
        }

        for (i = 0; i < candidate_count; i++)
        {
            if (effective_distance_max >= 0.0 &&
                candidate_distances[i] < effective_distance_max)
            {
                continue;
            }

            if (best_candidate < 0 ||
                candidate_distances[i] > candidate_distances[best_candidate])
            {
                best_candidate = i;
            }
        }

        if (best_candidate < 0)
        {
            break;
        }

        if (params->n_max > 0 && selected_count >= params->n_max)
        {
            goto cleanup;
        }

        i = candidate_indices[best_candidate];
        rows[i].selected = 1;
        rows[i].importance = next_importance;
        rows[i].distance = candidate_distances[best_candidate];

        selected_count++;
        next_importance++;
    }

cleanup:
    if (candidate_distances != NULL)
    {
        FNC_free(candidate_distances);
    }

    if (candidate_indices != NULL)
    {
        FNC_free(candidate_indices);
    }
}

static int count_selected_compact(CompactBuffer *rows, int row_count)
{
    int i;
    int count = 0;

    for (i = 0; i < row_count; i++)
    {
        if (compact_row_at(rows, i)->selected)
        {
            count++;
        }
    }

    return count;
}

static int find_best_compact_candidate(
    CompactBuffer *rows,
    int row_count,
    double *best_distance,
    double *max_distance
)
{
    int left = -1;
    int right = -1;
    int i;
    int global_best = -1;
    double global_best_distance = -1.0;
    double global_max_distance = -1.0;

    for (i = 0; i < row_count; i++)
    {
        CompactRow *right_row = compact_row_at(rows, i);
        if (right_row->selected)
        {
            right = i;

            if (left >= 0 && right > left + 1)
            {
                int j;
                int interval_best = -1;
                double interval_best_distance = -1.0;

                for (j = left + 1; j < right; j++)
                {
                    CompactRow *candidate_row = compact_row_at(rows, j);
                    if (!candidate_row->selected)
                    {
                        CompactRow *left_row = compact_row_at(rows, left);
                        double d = point_segment_distance(
                            candidate_row->x,
                            candidate_row->y,
                            left_row->x,
                            left_row->y,
                            right_row->x,
                            right_row->y
                        );

                        if (d > interval_best_distance)
                        {
                            interval_best_distance = d;
                            interval_best = j;
                        }
                    }
                }

                if (interval_best >= 0)
                {
                    if (interval_best_distance > global_max_distance)
                    {
                        global_max_distance = interval_best_distance;
                    }

                    if (interval_best_distance > global_best_distance)
                    {
                        global_best_distance = interval_best_distance;
                        global_best = interval_best;
                    }
                }
            }

            left = right;
        }
    }

    *best_distance = global_best_distance;
    *max_distance = global_max_distance;
    return global_best;
}

static void compress_compact_rows(
    CompactBuffer *rows,
    int row_count,
    const CompressionParams *params
)
{
    int selected_count;
    int next_importance;
    double initial_max_distance = -1.0;
    double effective_distance_max;

    if (row_count <= 0)
    {
        return;
    }

    compact_row_at(rows, 0)->selected = 1;
    compact_row_at(rows, 0)->importance = 1;
    compact_row_at(rows, 0)->distance = 0.0;

    if (row_count > 1)
    {
        compact_row_at(rows, row_count - 1)->selected = 1;
        compact_row_at(rows, row_count - 1)->importance = 2;
        compact_row_at(rows, row_count - 1)->distance = 0.0;
    }

    selected_count = count_selected_compact(rows, row_count);
    next_importance = selected_count + 1;
    effective_distance_max = params->distance_max;

    while (selected_count < row_count)
    {
        double best_distance = -1.0;
        double max_distance = -1.0;
        int best = find_best_compact_candidate(
            rows,
            row_count,
            &best_distance,
            &max_distance
        );

        if (best < 0)
        {
            break;
        }

        if (initial_max_distance < 0.0)
        {
            initial_max_distance = max_distance;
            if (params->n_max_auto && effective_distance_max < 0.0)
            {
                if (initial_max_distance <= MIN_TOLERANCE)
                {
                    break;
                }
                effective_distance_max =
                    initial_max_distance / pow(10.0, params->auto_log_drop);
                if (effective_distance_max < DEFAULT_DISTANCE_MAX)
                {
                    effective_distance_max = DEFAULT_DISTANCE_MAX;
                }
            }
        }

        if (effective_distance_max >= 0.0 && max_distance < effective_distance_max)
        {
            break;
        }

        if (effective_distance_max >= 0.0 && best_distance < effective_distance_max)
        {
            break;
        }

        if (params->n_max > 0 && selected_count >= params->n_max)
        {
            break;
        }

        compact_row_at(rows, best)->selected = 1;
        compact_row_at(rows, best)->importance = next_importance;
        compact_row_at(rows, best)->distance = best_distance;

        selected_count++;
        next_importance++;
    }
}

static int bind_original_attributes(
    FNC_TblOpHandle_t *output_handle,
    const BufferedRow *row,
    int column_count
)
{
    int i;
    int rc;

    for (i = 0; i < column_count; i++)
    {
        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            i,
            row->attrs[i].data,
            row->attrs[i].null_ind,
            row->attrs[i].length
        );

        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }
    }

    return TBLOP_SUCCESS;
}

static int write_selected_rows(
    FNC_TblOpHandle_t *output_handle,
    BufferedRow *rows,
    int row_count,
    int column_count
)
{
    int i;
    int rc;
    int data_column_count = column_count - 2;
    int importance_col_ndx = column_count - 2;
    int distance_col_ndx = column_count - 1;

    for (i = 0; i < row_count; i++)
    {
        if (!rows[i].selected)
        {
            continue;
        }

        rc = bind_original_attributes(output_handle, &rows[i], data_column_count);
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            importance_col_ndx,
            &(rows[i].importance),
            IS_NOT_NULL,
            sizeof(INTEGER)
        );
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            distance_col_ndx,
            &(rows[i].distance),
            IS_NOT_NULL,
            sizeof(double)
        );
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpWrite(output_handle);
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }
    }

    return TBLOP_SUCCESS;
}

static int write_selected_rows_compact(
    FNC_TblOpHandle_t *output_handle,
    CompactBuffer *rows,
    int row_count,
    const PartitionIds *partition_ids,
    const CompressionParams *params
)
{
    int i;
    int rc;
    double unit_seconds;

    unit_seconds = params->time_unit_seconds;
    if (unit_seconds <= MIN_TOLERANCE)
    {
        unit_seconds = 1.0;
    }

    for (i = 0; i < row_count; i++)
    {
        CompactRow *row = compact_row_at(rows, i);
        long long raw_time_bigint;
        double raw_y;
        INTEGER importance_value;
        double distance_value;
        int id_ndx;

        if (!row->selected)
        {
            continue;
        }

        raw_time_bigint = (long long)(
            ((row->x * params->tol_x) + params->norm_min_x)
            * unit_seconds
            + params->norm_base_x
            + 0.5
        );
        raw_y = (row->y * params->tol_y) + params->norm_min_y;
        importance_value = (INTEGER)row->importance;
        distance_value = (double)row->distance;

        for (id_ndx = 0; id_ndx < partition_ids->count; id_ndx++)
        {
            rc = FNC_TblOpBindAttributeByNdx(
                output_handle,
                id_ndx,
                partition_ids->ids[id_ndx].data,
                partition_ids->ids[id_ndx].null_ind,
                partition_ids->ids[id_ndx].length
            );
            if (rc != TBLOP_SUCCESS)
            {
                return rc;
            }
        }

        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            params->time_col_ndx,
            &raw_time_bigint,
            IS_NOT_NULL,
            sizeof(long long)
        );
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            params->value_col_ndx,
            &raw_y,
            IS_NOT_NULL,
            sizeof(double)
        );
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            params->value_col_ndx + 1,
            &importance_value,
            IS_NOT_NULL,
            sizeof(INTEGER)
        );
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpBindAttributeByNdx(
            output_handle,
            params->value_col_ndx + 2,
            &distance_value,
            IS_NOT_NULL,
            sizeof(double)
        );
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }

        rc = FNC_TblOpWrite(output_handle);
        if (rc != TBLOP_SUCCESS)
        {
            return rc;
        }
    }

    return TBLOP_SUCCESS;
}

void ts_compress_to(void)
{
    FNC_TblOpHandle_t *input_handle = NULL;
    FNC_TblOpHandle_t *output_handle = NULL;
    BufferedRow *rows = NULL;
    CompactBuffer compact_rows;
    PartitionIds partition_ids;
    CompressionParams params;
    int capacity = 0;
    int row_count = 0;
    int input_column_count;
    int compact_mode = 0;
    int rc;

    init_params(&params);
    memset(&compact_rows, 0, sizeof(CompactBuffer));
    memset(&partition_ids, 0, sizeof(PartitionIds));

    input_column_count = FNC_TblOpGetColCount(0, ISINPUT);
    if (input_column_count <= params.value_col_ndx || input_column_count < 5)
    {
        return;
    }

    input_handle = FNC_TblOpOpen(0, 'R', TBLOP_NOOPTIONS);
    if (input_handle == NULL)
    {
        return;
    }

    output_handle = FNC_TblOpOpen(0, 'W', TBLOP_NOOPTIONS);
    if (output_handle == NULL)
    {
        FNC_TblOpClose(input_handle);
        return;
    }

    load_custom_params(&params);
    compact_mode = (params.id_col_count > 0 &&
                    params.time_type == TIME_TYPE_NUMERIC &&
                    input_column_count == params.id_col_count + 4 &&
                    params.time_col_ndx == params.id_col_count &&
                    params.value_col_ndx == params.id_col_count + 1);

    if (compact_mode && !init_partition_ids(&partition_ids, params.id_col_count))
    {
        goto cleanup;
    }

    while (1)
    {
        rc = FNC_TblOpRead(input_handle);

        if (rc == TBLOP_EOF)
        {
            break;
        }

        if (rc != TBLOP_SUCCESS)
        {
            goto cleanup;
        }

        if (compact_mode)
        {
            if (!ensure_compact_capacity(&compact_rows, row_count + 1))
            {
                goto cleanup;
            }

            if (!buffer_current_row_compact(
                    input_handle,
                    compact_row_at(&compact_rows, row_count),
                    row_count,
                    &params,
                    &partition_ids))
            {
                goto cleanup;
            }
        }
        else
        {
            if (!ensure_capacity(&rows, &capacity, row_count + 1))
            {
                goto cleanup;
            }

            if (!buffer_current_row(
                        input_handle,
                        &rows[row_count],
                        input_column_count,
                        row_count,
                        &params))
            {
                goto cleanup;
            }
        }

        row_count++;
    }

    if (compact_mode)
    {
        normalize_compact_rows(&compact_rows, row_count, &params);
        compress_compact_rows(&compact_rows, row_count, &params);
        if (write_selected_rows_compact(
                output_handle,
                &compact_rows,
                row_count,
                &partition_ids,
                &params) != TBLOP_SUCCESS)
        {
            goto cleanup;
        }
    }
    else
    {
        normalize_buffered_rows(rows, row_count, &params);
        compress_rows(rows, row_count, &params);
        if (write_selected_rows(output_handle, rows, row_count, input_column_count) != TBLOP_SUCCESS)
        {
            goto cleanup;
        }
    }

cleanup:
    free_buffered_rows(rows, row_count, input_column_count);
    free_compact_rows(&compact_rows);
    free_partition_ids(&partition_ids);

    if (output_handle != NULL)
    {
        FNC_TblOpClose(output_handle);
    }

    if (input_handle != NULL)
    {
        FNC_TblOpClose(input_handle);
    }
}
