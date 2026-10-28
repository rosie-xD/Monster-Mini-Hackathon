"""Synthetic-only tests for the three standalone scripts."""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ghost import GhostDetector
from zombie import ZombieDetector, MINUTE, timestamp_us
from vampire import VampireDetector
import ghost
import zombie
import vampire

MODULES = (ghost, zombie, vampire)
EXAMPLES = ROOT / "examples" / "synthetic"

def classify_ghost(weeks):
    detector = GhostDetector()
    for index, week in enumerate(weeks):
        detector.add(index, week, "LMS" if index % 2 else "video")
    return detector.finish()


class GhostTests(unittest.TestCase):
    def test_three_early_weeks_with_no_later_activity(self):
        result = classify_ghost([1, 2, 3])
        self.assertTrue(result.matched)
        self.assertEqual(result.evidence["early_weekly_average"], .75)
        self.assertEqual(result.evidence["later_weekly_average"], 0)

    def test_two_active_weeks_are_insufficient_even_with_many_rows(self):
        self.assertFalse(classify_ghost([1] * 100 + [4] * 100).matched)

    def test_exact_ten_percent_fails_and_just_below_passes(self):
        early = [1] * 4 + [2] * 3 + [4] * 3
        self.assertFalse(classify_ghost(early + [5] * 12).matched)
        result = classify_ghost(early + [52] * 11)
        self.assertTrue(result.matched)
        self.assertEqual(result.evidence["later_weekly_average"], 11 / 48)

    def test_no_early_activity_is_not_a_ghost(self):
        result = classify_ghost([20, 21, 22])
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence["later_to_early_ratio"], "")

    def test_requires_valid_calendar_week(self):
        for week in (None, 0, 53):
            with self.subTest(week=week), self.assertRaises(ValueError):
                GhostDetector().add(0, week, "LMS")


START = timestamp_us("2023-10-02T23:00:00Z", None)


def classify_zombie(offsets):
    detector = ZombieDetector()
    for i, offset in enumerate(offsets):
        detector.add(START + offset, None, "LMS" if i % 2 else "video")
    return detector.finish()


class ZombieTests(unittest.TestCase):
    def test_exact_three_hours_fails_one_microsecond_over_passes(self):
        offsets = [i * 15 * MINUTE for i in range(13)]
        self.assertFalse(classify_zombie(offsets).matched)
        result = classify_zombie(offsets + [offsets[-1] + 1])
        self.assertTrue(result.matched)
        self.assertEqual(result.sequences[0]["max_gap_minutes"], 15)
        self.assertEqual(result.sequences[0]["activity_rows"], 14)

    def test_gap_over_fifteen_minutes_breaks_the_sequence(self):
        offsets = [i * 15 * MINUTE + (1 if i >= 7 else 0) for i in range(14)]
        self.assertFalse(classify_zombie(offsets).matched)

    def test_multiple_sequences_across_midnight_are_reported(self):
        first = [i * 15 * MINUTE for i in range(14)]
        second = [value + 400 * MINUTE for value in first]
        result = classify_zombie(first + second)
        self.assertEqual(len(result.sequences), 2)
        self.assertEqual(result.sequences[0]["end_utc"], "2023-10-03T02:15:00Z")
        self.assertEqual(result.evidence["longest_sequence_minutes"], 195)

    def test_duplicates_do_not_create_elapsed_time(self):
        result = classify_zombie([0] * 200)
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence["longest_sequence_minutes"], 0)

    def test_unsorted_timestamps_fail(self):
        with self.assertRaisesRegex(ValueError, "sorted"):
            classify_zombie([MINUTE, 0])


def classify_vampire(stamps, zone="UTC"):
    detector = VampireDetector(ZoneInfo(zone))
    for i, stamp in enumerate(stamps):
        detector.add(timestamp_us(stamp, None), None, "LMS" if i % 2 else "video")
    return detector.finish()


def dates(count, clock="02:00:00"):
    return [f"{date(2024, 1, 1) + timedelta(days=n)}T{clock}Z" for n in range(count)]


class VampireTests(unittest.TestCase):
    def test_twenty_one_fails_twenty_two_passes(self):
        self.assertFalse(classify_vampire(dates(21)).matched)
        self.assertTrue(classify_vampire(dates(22)).matched)

    def test_distinct_dates_not_number_of_events(self):
        result = classify_vampire(dates(1) * 100)
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence["night_days"], 1)

    def test_night_day_tie_fails_and_same_date_can_count_in_both(self):
        result = classify_vampire(dates(22) + dates(22, "12:00:00"))
        self.assertFalse(result.matched)
        self.assertEqual(result.evidence, {"night_days": 22, "day_days": 22})
        self.assertTrue(classify_vampire(dates(22) + dates(21, "12:00:00")).matched)

    def test_midnight_counts_as_previous_day_five_am_counts_as_night(self):
        result = classify_vampire(["2024-01-02T00:00:00Z", "2024-01-02T00:00:00.000001Z",
                           "2024-01-02T05:00:00Z", "2024-01-02T05:00:00.000001Z"])
        self.assertEqual(result.evidence, {"night_days": 1, "day_days": 2})

    def test_timezone_conversion_changes_clock_and_date(self):
        stamp = ["2024-07-01T04:30:00Z"]
        self.assertEqual(classify_vampire(stamp).evidence["night_days"], 1)
        self.assertEqual(classify_vampire(stamp, "Europe/London").evidence["day_days"], 1)
        # UK midnight is the prior daytime date under the preserved convention.
        result = classify_vampire(["2024-07-01T22:00:00Z", "2024-07-01T23:00:00Z"], "Europe/London")
        self.assertEqual(result.evidence["day_days"], 1)



class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, module, lms=None, video=None, extra=(), calendar=True, script=None):
        args = [sys.executable, str(script or ROOT / f'{module.MONSTER.lower()}.py'),
                '--lms', str(lms or EXAMPLES / 'lms.csv'),
                '--video', str(video or EXAMPLES / 'video.csv')]
        if calendar:
            args += ['--calendar', str(EXAMPLES / 'calendar.csv')]
        return subprocess.run(args + list(map(str, extra)), cwd=self.path,
                              text=True, capture_output=True)

    def output(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.path / json.loads(result.stdout)['output']

    def read(self, path):
        with path.open(encoding='utf-8', newline='') as stream:
            return list(csv.DictReader(stream))

    def test_each_script_runs_alone_without_repository_imports(self):
        expected = json.loads((EXAMPLES / 'expected_findings.json').read_text())
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                # Only this single .py file is copied, outside the repository.
                script = self.path / f'{module.MONSTER.lower()}.py'
                shutil.copyfile(ROOT / script.name, script)
                result = self.execute(module, script=script)
                output = self.output(result)
                self.assertEqual(self.read(output / 'findings.csv'),
                                 [r for r in expected if r['Monster Type'] == module.MONSTER])
                evidence = self.read(output / 'student_evidence.csv')
                self.assertEqual(len(evidence), 9)
                self.assertEqual(output.parent.name, module.MONSTER.lower())
                summary = json.loads((output / 'run_summary.json').read_text())
                self.assertTrue(summary['completed'])
                self.assertEqual(summary['rows']['LMS']['included'], 68)
                self.assertEqual(summary['rows']['video']['included'], 86)
                if module is zombie:
                    sequence = self.read(output / 'zombie_sequences.csv')
                    self.assertEqual(len(sequence), 1)
                    self.assertEqual(float(sequence[0]['duration_minutes']), 195)
                self.assertEqual(list(output.glob('working-*')), [])

    def test_zip_inputs_match_csv_for_each_script(self):
        archive = self.path / 'video.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(EXAMPLES / 'video.csv', 'video.csv')
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                csv_out = self.output(self.execute(module))
                zip_out = self.output(self.execute(module, video=archive))
                self.assertEqual((csv_out/'findings.csv').read_bytes(), (zip_out/'findings.csv').read_bytes())
                self.assertEqual((csv_out/'student_evidence.csv').read_bytes(),
                                 (zip_out/'student_evidence.csv').read_bytes())

    def test_csv_byte_parts_reassemble_without_headers_on_each_part(self):
        content = (EXAMPLES / 'lms.csv').read_bytes()
        parts=[]
        for n, chunk in enumerate((content[:101], content[101:223], content[223:])):
            path=self.path/f'part_{n}';path.write_bytes(chunk);parts.append(path)
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                result=subprocess.run([sys.executable, str(ROOT/f'{module.MONSTER.lower()}.py'),
                    '--lms-parts', *map(str,reversed(parts)), '--video', str(EXAMPLES/'video.csv'),
                    '--calendar', str(EXAMPLES/'calendar.csv')], cwd=self.path, capture_output=True, text=True)
                output=self.output(result)
                expected=[r for r in json.loads((EXAMPLES/'expected_findings.json').read_text())
                          if r['Monster Type']==module.MONSTER]
                self.assertEqual(self.read(output/'findings.csv'),expected)
                # Splits inside a multibyte character must also be reconstructed.
                data='P_ID,TIMESTAMP\nétudiant,2023-10-02T01:00:00Z\n'.encode('utf-8-sig')
                cut=data.index('é'.encode())+1
                a=self.path/'utf_a';b=self.path/'utf_b'
                a.write_bytes(data[:cut]);b.write_bytes(data[cut:])
                with module.csv_stream([a,b],parts=True) as stream:
                    self.assertEqual(stream.read(),data.decode('utf-8-sig'))

    def test_default_outputs_are_unique_and_existing_output_is_protected(self):
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                first=self.output(self.execute(module));second=self.output(self.execute(module))
                self.assertNotEqual(first,second)
                before=(first/'findings.csv').read_bytes()
                result=self.execute(module,extra=['--output',first])
                self.assertEqual(result.returncode,2)
                self.assertIn('already exists',result.stderr)
                self.assertEqual((first/'findings.csv').read_bytes(),before)

    def test_calendar_required_only_for_ghost(self):
        result=self.execute(ghost,calendar=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('--calendar',result.stderr)
        for module in (zombie,vampire):
            with self.subTest(monster=module.MONSTER):
                self.output(self.execute(module,calendar=False))

    def test_bad_timestamp_and_header_fail_with_no_success_summary(self):
        for module in MODULES:
            for header,value,expected in [('P_ID,TIMESTAMP,DATE','bad,broken,2023-10-02','line 2'),
                                          ('wrong,headers,here','x,y,z','missing headers')]:
                with self.subTest(monster=module.MONSTER,expected=expected):
                    file=self.path/'bad.csv';file.write_text(header+'\n'+value+'\n')
                    output=self.path/f'{module.MONSTER}-{expected.replace(" ","-")}'
                    result=self.execute(module,lms=file,extra=['--output',output])
                    self.assertEqual(result.returncode,2)
                    self.assertIn(expected,result.stderr)
                    self.assertFalse((output/'run_summary.json').exists())
                    self.assertEqual(list(output.glob('working-*')),[])

    def test_calendar_rejects_missing_week_duplicate_date_and_unmatched_activity(self):
        calendar=self.path/'calendar.csv'
        original=(EXAMPLES/'calendar.csv').read_text()
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                calendar.write_text('\n'.join(original.splitlines()[:-7])+'\n')
                with self.assertRaises(ValueError):module.load_calendar(calendar,None)
                calendar.write_text(original+original.splitlines()[1]+'\n')
                with self.assertRaisesRegex(ValueError,'duplicate DATE'):module.load_calendar(calendar,None)
                invalid=self.path/'old.csv'
                invalid.write_text('P_ID,TIMESTAMP,DATE\nx,2022-01-01T12:00:00Z,2022-01-01\n')
                result=self.execute(module,lms=invalid)
                self.assertEqual(result.returncode,2)
                self.assertIn('absent from calendar',result.stderr)

    def test_naive_and_dst_ambiguous_timestamps_require_explicit_offsets(self):
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                with self.assertRaises(ValueError):module.timestamp_us('2023-10-02T12:00:00',None)
                self.assertEqual(module.timestamp_us('2023-10-02T12:00:00',ZoneInfo('UTC')),
                                 module.timestamp_us('2023-10-02T12:00:00Z',None))
                with self.assertRaises(ValueError):
                    module.timestamp_us('2024-10-27T01:30:00',ZoneInfo('Europe/London'))

    def test_streaming_batches_preserve_100002_rows(self):
        lms=self.path/'large.csv';video=self.path/'small.csv'
        header='P_ID,TIMESTAMP,DATE\n'
        row='synthetic,2024-01-02T12:00:00Z,2024-01-02\n'
        with lms.open('w') as f:
            f.write(header)
            for _ in range(100001):f.write(row)
        video.write_text(header+row)
        for module in MODULES:
            with self.subTest(monster=module.MONSTER):
                output=self.output(self.execute(module,lms=lms,video=video))
                evidence=self.read(output/'student_evidence.csv')
                self.assertEqual(len(evidence),1)
                self.assertEqual(int(evidence[0]['activity_rows']),100002)
                self.assertEqual(self.read(output/'findings.csv'),[])

    def test_multiple_complete_csvs_preserve_findings(self):
        with (EXAMPLES/'lms.csv').open() as f: records=list(csv.reader(f))
        paths=[self.path/'a.csv',self.path/'b.csv']
        for path,subset in zip(paths,(records[1::2],records[2::2])):
            with path.open('w',newline='') as f:
                writer=csv.writer(f);writer.writerow(records[0]);writer.writerows(subset)
        for module in MODULES:
            result=subprocess.run([sys.executable,str(ROOT/f'{module.MONSTER.lower()}.py'),
                '--lms',*map(str,paths),'--video',str(EXAMPLES/'video.csv'),
                '--calendar',str(EXAMPLES/'calendar.csv')],cwd=self.path,capture_output=True,text=True)
            output=self.output(result)
            expected=[r for r in json.loads((EXAMPLES/'expected_findings.json').read_text())
                      if r['Monster Type']==module.MONSTER]
            self.assertEqual(self.read(output/'findings.csv'),expected)


if __name__ == '__main__':
    unittest.main()
