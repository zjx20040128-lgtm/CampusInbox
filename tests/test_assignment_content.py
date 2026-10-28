import unittest
from courseinbox.chaoxing import task_content_url


class AssignmentContentTests(unittest.TestCase):
    def test_assignment_content_routes_are_not_arbitrary_urls(self):
        url='https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=1&classId=2&workId=42&answerId=7'
        self.assertEqual(task_content_url(url),url)
        self.assertEqual(task_content_url(url.replace('/task?', '/dowork?')),url.replace('/task?', '/dowork?'))
        for bad in (url+'&submit=1',url.replace('/task?', '/save?'),url.replace('mooc1.chaoxing.com','example.com'),url+'&workId=99',url.replace('workId=42','examId=42')):
            self.assertEqual(task_content_url(bad),'')


if __name__=='__main__':unittest.main()
