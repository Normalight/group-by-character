"""独立工作进程：只写任务临时目录，不发布正式输出。"""
from grouping.service import PPOcrV6CharacterRecognizer, iter_image_files, run_grouping


def run_job(connection, options, scan, records, result_dir):
    try:
        opts = options.copy()
        model, yaml = opts.pop('model'), opts.pop('yaml')
        files = iter_image_files(opts['input_dir'], excluded_dir=opts['output_dir'],
                                 input_format=opts['input_format']) if records is None else []
        if scan:
            connection.send(('completed', {'scan_count': len(files)}))
            return
        # Keep discovery based on the real output exclusion even though generation
        # occurs in a separate job directory.
        if records is None and not files:
            connection.send(('completed', {'output_dir': opts['output_dir'], 'record_count': 0,
                                           'group_count': 0, 'review_count': 0, 'unrecognized_count': 0}))
            return
        recognizer = PPOcrV6CharacterRecognizer(model, yaml or None) if records is None else None
        if records is None:
            # Explicit file discovery is passed separately to keep OCR enabled.
            opts['source_files'] = files
        if records is not None:
            opts['reuse_dir'] = opts['output_dir']
        opts['output_dir'] = result_dir
        result = run_grouping(**opts, recognizer=recognizer, records_override=records,
                              progress=lambda *args: connection.send(('progress', args)))
        connection.send(('completed', result))
    except Exception as exc:
        connection.send(('failed', str(exc)))
    finally:
        connection.close()
