// SPDX-License-Identifier: GPL-3.0-only
/*
 *  Minecraft Server Manager - FlexVersion
 *  Copyright (C) 2025-2026 Colin955023
 *
 *  This file is a C# translation and modification of launcher/Version.h and
 *  launcher/Version.cpp from Prism Launcher (https://github.com/PrismLauncher/PrismLauncher),
 *  translated and modified by Colin955023 on 2026-10-14. The original work carries
 *  the following notice:
 *
 *      Prism Launcher - Minecraft Launcher
 *      Copyright (C) 2023 flowln <flowlnlnln@gmail.com>
 *      Copyright (C) 2022 Sefa Eyeoglu <contact@scrumplex.net>
 *      Copyright (c) 2026 Trial97 <alexandru.tripon97@gmail.com>
 *
 *  This program is free software: you can redistribute it and/or modify
 *  it under the terms of the GNU General Public License as published by
 *  the Free Software Foundation, version 3.
 *
 *  This program is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU General Public License for more details.
 *
 *  You should have received a copy of the GNU General Public License
 *  along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

using MinecraftServerManager.Domain.ValueObjects;

namespace MinecraftServerManager.Domain.Mods;

/// <summary>彈性版本比較（移植自 Prism Launcher，授權見檔案開頭與 COPYING.md）</summary>
public sealed class FlexVersion : IComparable<FlexVersion>
{
    private enum SectionType : byte
    {
        Null = 0,
        Textual = 1,
        Numeric = 2,
        PreRelease = 3,
    }

    /// <summary>版本區段：記錄於原始字串之位置，避免配置子字串</summary>
    private readonly record struct Section(SectionType Type, int Start, int Length)
    {
        public static readonly Section Null = new(SectionType.Null, 0, 0);
    }

    private readonly string _raw;
    private readonly List<Section> _sections;

    public FlexVersion(string? raw)
    {
        _raw = raw ?? string.Empty;
        _sections = ParseSections(_raw);
    }

    /// <summary>比較兩個模組版本字串之新舊先後關係</summary>
    public static int Compare(string? a, string? b)
    {
        if (string.Equals(a, b, StringComparison.OrdinalIgnoreCase))
        {
            return 0;
        }

        var vA = new FlexVersion(NormalizeModVersionString(a));
        var vB = new FlexVersion(NormalizeModVersionString(b));
        return vA.CompareTo(vB);
    }

    /// <summary>正規化模組版本字串（去除 v/V 與 mc1.x- 等常見前綴）</summary>
    public static string NormalizeModVersionString(string? raw)
    {
        if (string.IsNullOrWhiteSpace(raw))
        {
            return string.Empty;
        }

        ReadOnlySpan<char> span = raw.AsSpan().Trim();

        // 去除開頭的 'v' 或 'V' (若其後直接接數字，例如 v1.2.0 -> 1.2.0)
        if (span.Length > 1 && span[0] is 'v' or 'V' && char.IsAsciiDigit(span[1]))
        {
            span = span[1..];
        }

        // 去除常見 Minecraft 版本前綴，如 mc1.21.1-0.15.2 或 1.21-15.1.4
        if (span.StartsWith("mc", StringComparison.OrdinalIgnoreCase) && span.Length > 2 && char.IsAsciiDigit(span[2]))
        {
            int sepIndex = span.IndexOfAny('-', '_');
            if (sepIndex > 2 && sepIndex + 1 < span.Length && char.IsAsciiDigit(span[sepIndex + 1])
                && IsMinecraftVersionPrefix(span[2..sepIndex]))
            {
                span = span[(sepIndex + 1)..];
            }
        }
        else if (char.IsAsciiDigit(span[0]))
        {
            int firstDash = span.IndexOf('-');
            if (firstDash > 0 && firstDash + 1 < span.Length && char.IsAsciiDigit(span[firstDash + 1]))
            {
                ReadOnlySpan<char> remainder = span[(firstDash + 1)..];
                if (IsMinecraftVersionPrefix(span[..firstDash]) && remainder.Contains('.'))
                {
                    span = remainder;
                }
            }
        }

        return span.ToString();
    }

    /// <summary>判斷是否為 Minecraft 正式版號：1.x（x ≥ 2）或 26.x 以後之年份版號，最多三段純數字</summary>
    private static bool IsMinecraftVersionPrefix(ReadOnlySpan<char> text)
    {
        Span<int> values = stackalloc int[3];
        if (!DotSeparatedIntParser.TryParse(text, values, out int count) || count is < 2 or > 3)
        {
            return false;
        }

        return values[0] == 1 ? values[1] >= 2 : values[0] >= 26;
    }

    private static List<Section> ParseSections(string raw)
    {
        var sections = new List<Section>();
        ReadOnlySpan<char> span = raw.AsSpan();
        int len = span.Length;

        for (int i = 0; i < len;)
        {
            char c = span[i];
            if (c == '+')
            {
                // 依照 FlexVer 規範：忽略 '+' 之後的建置中繼資料 (Build Metadata)
                break;
            }

            var type = SectionType.Textual;
            int start = i;

            if (c is '-' or ' ')
            {
                i++;
                if (i < len && !char.IsAsciiDigit(span[i]))
                {
                    type = SectionType.PreRelease;
                }
            }
            else if (char.IsAsciiDigit(c))
            {
                type = SectionType.Numeric;
            }

            while (i < len)
            {
                char r = span[i];
                if (char.IsAsciiDigit(r) != (type == SectionType.Numeric)
                    || (r is '-' or ' ' && type != SectionType.PreRelease)
                    || r == '+')
                {
                    break;
                }
                i++;
            }

            int length = i - start;
            if (type == SectionType.Numeric)
            {
                // 消除前導零
                while (length > 0 && span[start] == '0')
                {
                    start++;
                    length--;
                }
            }

            if (length > 0 || type == SectionType.Numeric)
            {
                sections.Add(new Section(type, start, length));
            }
        }

        return sections;
    }

    private int CompareSection(Section a, FlexVersion other, Section b)
    {
        ReadOnlySpan<char> valueA = _raw.AsSpan(a.Start, a.Length);
        ReadOnlySpan<char> valueB = other._raw.AsSpan(b.Start, b.Length);

        if (a.Type == SectionType.Numeric && b.Type == SectionType.Numeric)
        {
            return NumericSegmentComparer.Compare(valueA, valueB);
        }

        if (a.Type == SectionType.Null && b.Type == SectionType.Null)
        {
            return 0;
        }

        // 正式版 (Null) 優先於 PreRelease 版
        if (a.Type == SectionType.Null)
        {
            return b.Type == SectionType.PreRelease ? 1 : -1;
        }
        if (b.Type == SectionType.Null)
        {
            return a.Type == SectionType.PreRelease ? -1 : 1;
        }

        return valueA.CompareTo(valueB, StringComparison.OrdinalIgnoreCase);
    }

    public int CompareTo(FlexVersion? other)
    {
        if (ReferenceEquals(this, other))
        {
            return 0;
        }
        if (other is null)
        {
            return 1;
        }

        int maxSections = Math.Max(_sections.Count, other._sections.Count);
        for (int i = 0; i < maxSections; i++)
        {
            var secA = i < _sections.Count ? _sections[i] : Section.Null;
            var secB = i < other._sections.Count ? other._sections[i] : Section.Null;

            int cmp = CompareSection(secA, other, secB);
            if (cmp != 0)
            {
                return cmp;
            }
        }

        return 0;
    }

    public override bool Equals(object? obj) => obj is FlexVersion other && CompareTo(other) == 0;

    public override int GetHashCode()
    {
        var hash = new HashCode();
        hash.Add(_sections.Count);
        foreach (var section in _sections)
        {
            hash.Add(string.GetHashCode(_raw.AsSpan(section.Start, section.Length), StringComparison.OrdinalIgnoreCase));
        }

        return hash.ToHashCode();
    }

    public static bool operator ==(FlexVersion? left, FlexVersion? right) => left is null ? right is null : left.Equals(right);

    public static bool operator !=(FlexVersion? left, FlexVersion? right) => !(left == right);

    public static bool operator <(FlexVersion? left, FlexVersion? right) => left is null ? right is not null : left.CompareTo(right) < 0;

    public static bool operator <=(FlexVersion? left, FlexVersion? right) => left is null || left.CompareTo(right) <= 0;

    public static bool operator >(FlexVersion? left, FlexVersion? right) => left is not null && left.CompareTo(right) > 0;

    public static bool operator >=(FlexVersion? left, FlexVersion? right) => left is null ? right is null : left.CompareTo(right) >= 0;
}
