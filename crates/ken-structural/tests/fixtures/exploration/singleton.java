class Subject { static Subject instance=null;
 static Subject shared(){if(Subject.instance==null){Subject.instance=new Subject();}return Subject.instance;}
}
